// SPDX-License-Identifier: GPL-2.0
/*
 * qpu_driver: mediates quantum job dispatch between a client and a
 * userspace execution backend, the way a GPU driver mediates between
 * an application and the userspace runtime that actually talks to the
 * card. This module never looks at QASM or JSON content - it only
 * tracks qubit capacity as a plain counter and moves opaque byte
 * blobs between two device nodes:
 *
 *   /dev/qpu0        - client: submit a job, query its status/result
 *   /dev/qpu0worker  - execution backend: fetch the next pending job
 *                      (blocks until one exists), report completion
 */

#include <linux/atomic.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/idr.h>
#include <linux/list.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/sysfs.h>
#include <linux/uaccess.h>
#include <linux/wait.h>

#include "qpu_ioctl.h"

static int qpu_total_qubits = 32;
module_param(qpu_total_qubits, int, 0444);
MODULE_PARM_DESC(qpu_total_qubits, "total qubit capacity advertised by this backend");

static atomic_t qpu_qubits_in_use = ATOMIC_INIT(0);
static atomic_t qpu_jobs_submitted = ATOMIC_INIT(0);
static atomic_t qpu_jobs_completed = ATOMIC_INIT(0);
static atomic_t qpu_jobs_failed = ATOMIC_INIT(0);

static DEFINE_IDR(qpu_jobs);
static DEFINE_MUTEX(qpu_lock);
static LIST_HEAD(qpu_pending);
static DECLARE_WAIT_QUEUE_HEAD(qpu_pending_wq);

struct qpu_job {
	int id;
	u32 num_qubits;
	u32 shots;
	u32 qasm_len;
	char *qasm;
	enum qpu_job_status state;
	u32 result_len;
	char *result;
	struct list_head pending_link;
};

static struct qpu_job *qpu_job_alloc(u32 num_qubits, u32 shots,
				      const char *qasm, u32 qasm_len)
{
	struct qpu_job *job = kzalloc(sizeof(*job), GFP_KERNEL);

	if (!job)
		return NULL;

	job->qasm = kmalloc(qasm_len, GFP_KERNEL);
	if (!job->qasm) {
		kfree(job);
		return NULL;
	}
	memcpy(job->qasm, qasm, qasm_len);
	job->qasm_len = qasm_len;
	job->num_qubits = num_qubits;
	job->shots = shots;
	job->state = QPU_JOB_PENDING;
	INIT_LIST_HEAD(&job->pending_link);
	return job;
}

static void qpu_job_free(struct qpu_job *job)
{
	kfree(job->qasm);
	kfree(job->result);
	kfree(job);
}

/* ---- /dev/qpu0 (client) ---- */

static long qpu_client_submit(struct qpu_submit __user *uarg)
{
	struct qpu_submit *arg;
	struct qpu_job *job;
	int id;
	long ret = 0;

	arg = kmalloc(sizeof(*arg), GFP_KERNEL);
	if (!arg)
		return -ENOMEM;

	if (copy_from_user(arg, uarg, sizeof(*arg))) {
		ret = -EFAULT;
		goto out;
	}

	if (arg->qasm_len == 0 || arg->qasm_len > QPU_QASM_MAX) {
		ret = -EINVAL;
		goto out;
	}

	mutex_lock(&qpu_lock);
	if (atomic_read(&qpu_qubits_in_use) + (int)arg->num_qubits > qpu_total_qubits) {
		mutex_unlock(&qpu_lock);
		ret = -ENOSPC;
		goto out;
	}
	atomic_add(arg->num_qubits, &qpu_qubits_in_use);
	mutex_unlock(&qpu_lock);

	job = qpu_job_alloc(arg->num_qubits, arg->shots, arg->qasm, arg->qasm_len);
	if (!job) {
		atomic_sub(arg->num_qubits, &qpu_qubits_in_use);
		ret = -ENOMEM;
		goto out;
	}

	mutex_lock(&qpu_lock);
	id = idr_alloc(&qpu_jobs, job, 1, 0, GFP_KERNEL);
	if (id < 0) {
		mutex_unlock(&qpu_lock);
		atomic_sub(arg->num_qubits, &qpu_qubits_in_use);
		qpu_job_free(job);
		ret = id;
		goto out;
	}
	job->id = id;
	list_add_tail(&job->pending_link, &qpu_pending);
	mutex_unlock(&qpu_lock);

	atomic_inc(&qpu_jobs_submitted);
	wake_up_interruptible(&qpu_pending_wq);

	arg->job_id = id;
	if (copy_to_user(uarg, arg, sizeof(*arg)))
		ret = -EFAULT;

out:
	kfree(arg);
	return ret;
}

static long qpu_client_query(struct qpu_query __user *uarg)
{
	struct qpu_query *arg;
	struct qpu_job *job;
	u32 len;
	long ret = 0;

	arg = kmalloc(sizeof(*arg), GFP_KERNEL);
	if (!arg)
		return -ENOMEM;

	if (copy_from_user(arg, uarg, sizeof(*arg))) {
		ret = -EFAULT;
		goto out;
	}

	mutex_lock(&qpu_lock);
	job = idr_find(&qpu_jobs, (int)arg->job_id);
	if (!job) {
		mutex_unlock(&qpu_lock);
		ret = -ENOENT;
		goto out;
	}

	arg->status = job->state;
	arg->result_len = 0;
	if (job->state == QPU_JOB_DONE || job->state == QPU_JOB_FAILED) {
		len = job->result_len;
		if (len > QPU_RESULT_MAX)
			len = QPU_RESULT_MAX;
		memcpy(arg->result, job->result, len);
		arg->result_len = len;
	}
	mutex_unlock(&qpu_lock);

	if (copy_to_user(uarg, arg, sizeof(*arg)))
		ret = -EFAULT;

out:
	kfree(arg);
	return ret;
}

static long qpu_client_ioctl(struct file *f, unsigned int cmd, unsigned long argp)
{
	switch (cmd) {
	case QPU_IOC_SUBMIT:
		return qpu_client_submit((struct qpu_submit __user *)argp);
	case QPU_IOC_QUERY:
		return qpu_client_query((struct qpu_query __user *)argp);
	default:
		return -ENOTTY;
	}
}

static const struct file_operations qpu_client_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = qpu_client_ioctl,
};

static struct miscdevice qpu_client_dev = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "qpu0",
	.fops = &qpu_client_fops,
	.mode = 0666,
};

/* ---- /dev/qpu0worker (execution backend) ---- */

static long qpu_worker_fetch(struct qpu_fetch __user *uarg)
{
	struct qpu_fetch *arg;
	struct qpu_job *job;
	int ret;

	arg = kzalloc(sizeof(*arg), GFP_KERNEL);
	if (!arg)
		return -ENOMEM;

	ret = wait_event_interruptible(qpu_pending_wq, !list_empty(&qpu_pending));
	if (ret)
		goto out;

	mutex_lock(&qpu_lock);
	if (list_empty(&qpu_pending)) {
		mutex_unlock(&qpu_lock);
		ret = -EAGAIN;
		goto out;
	}
	job = list_first_entry(&qpu_pending, struct qpu_job, pending_link);
	list_del_init(&job->pending_link);
	job->state = QPU_JOB_RUNNING;

	arg->job_id = job->id;
	arg->num_qubits = job->num_qubits;
	arg->shots = job->shots;
	arg->qasm_len = job->qasm_len;
	memcpy(arg->qasm, job->qasm, job->qasm_len);
	mutex_unlock(&qpu_lock);

	if (copy_to_user(uarg, arg, sizeof(*arg)))
		ret = -EFAULT;
	else
		ret = 0;

out:
	kfree(arg);
	return ret;
}

static long qpu_worker_complete(struct qpu_complete __user *uarg)
{
	struct qpu_complete *arg;
	struct qpu_job *job;
	long ret = 0;

	arg = kmalloc(sizeof(*arg), GFP_KERNEL);
	if (!arg)
		return -ENOMEM;

	if (copy_from_user(arg, uarg, sizeof(*arg))) {
		ret = -EFAULT;
		goto out;
	}

	if (arg->result_len > QPU_RESULT_MAX) {
		ret = -EINVAL;
		goto out;
	}

	mutex_lock(&qpu_lock);
	job = idr_find(&qpu_jobs, (int)arg->job_id);
	if (!job) {
		mutex_unlock(&qpu_lock);
		ret = -ENOENT;
		goto out;
	}

	job->result = kmalloc(arg->result_len, GFP_KERNEL);
	if (!job->result) {
		mutex_unlock(&qpu_lock);
		ret = -ENOMEM;
		goto out;
	}
	memcpy(job->result, arg->result, arg->result_len);
	job->result_len = arg->result_len;
	job->state = arg->ok ? QPU_JOB_DONE : QPU_JOB_FAILED;

	atomic_sub(job->num_qubits, &qpu_qubits_in_use);
	mutex_unlock(&qpu_lock);

	if (arg->ok)
		atomic_inc(&qpu_jobs_completed);
	else
		atomic_inc(&qpu_jobs_failed);

out:
	kfree(arg);
	return ret;
}

static long qpu_worker_ioctl(struct file *f, unsigned int cmd, unsigned long argp)
{
	switch (cmd) {
	case QPU_IOC_FETCH:
		return qpu_worker_fetch((struct qpu_fetch __user *)argp);
	case QPU_IOC_COMPLETE:
		return qpu_worker_complete((struct qpu_complete __user *)argp);
	default:
		return -ENOTTY;
	}
}

static const struct file_operations qpu_worker_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = qpu_worker_ioctl,
};

static struct miscdevice qpu_worker_dev = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "qpu0worker",
	.fops = &qpu_worker_fops,
	.mode = 0666,
};

/* ---- sysfs: capability + telemetry attributes under /sys/class/misc/qpu0/ ---- */

static ssize_t qubits_total_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", qpu_total_qubits);
}
static DEVICE_ATTR_RO(qubits_total);

static ssize_t qubits_in_use_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", atomic_read(&qpu_qubits_in_use));
}
static DEVICE_ATTR_RO(qubits_in_use);

static ssize_t jobs_submitted_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", atomic_read(&qpu_jobs_submitted));
}
static DEVICE_ATTR_RO(jobs_submitted);

static ssize_t jobs_completed_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", atomic_read(&qpu_jobs_completed));
}
static DEVICE_ATTR_RO(jobs_completed);

static ssize_t jobs_failed_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", atomic_read(&qpu_jobs_failed));
}
static DEVICE_ATTR_RO(jobs_failed);

static struct attribute *qpu_attrs[] = {
	&dev_attr_qubits_total.attr,
	&dev_attr_qubits_in_use.attr,
	&dev_attr_jobs_submitted.attr,
	&dev_attr_jobs_completed.attr,
	&dev_attr_jobs_failed.attr,
	NULL,
};

static const struct attribute_group qpu_attr_group = {
	.attrs = qpu_attrs,
};

/* ---- module init/exit ---- */

static int __init qpu_init(void)
{
	int ret;

	ret = misc_register(&qpu_client_dev);
	if (ret)
		return ret;

	ret = misc_register(&qpu_worker_dev);
	if (ret) {
		misc_deregister(&qpu_client_dev);
		return ret;
	}

	ret = sysfs_create_group(&qpu_client_dev.this_device->kobj, &qpu_attr_group);
	if (ret) {
		misc_deregister(&qpu_worker_dev);
		misc_deregister(&qpu_client_dev);
		return ret;
	}

	pr_info("qpu0: registered, capacity=%d qubits\n", qpu_total_qubits);
	return 0;
}

static void __exit qpu_exit(void)
{
	struct qpu_job *job;
	int id;

	sysfs_remove_group(&qpu_client_dev.this_device->kobj, &qpu_attr_group);
	misc_deregister(&qpu_worker_dev);
	misc_deregister(&qpu_client_dev);

	idr_for_each_entry(&qpu_jobs, job, id)
		qpu_job_free(job);
	idr_destroy(&qpu_jobs);

	pr_info("qpu0: unregistered\n");
}

module_init(qpu_init);
module_exit(qpu_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("qkernel");
MODULE_DESCRIPTION("Character device mediating quantum job dispatch between a client and a userspace execution backend");
