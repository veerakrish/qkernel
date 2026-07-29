#ifndef QPU_IOCTL_H
#define QPU_IOCTL_H

#include <linux/types.h>
#include <linux/ioctl.h>

/*
 * Every struct here is packed so the byte layout is unambiguous and
 * reproducible from userspace without relying on a matching compiler ABI.
 * The Python side mirrors these exactly with struct.pack/unpack using a
 * '<' (little-endian, no padding) format string — see daemon/kdevice.py.
 * If you change a struct here, update the matching Python format string.
 */

#define QPU_QASM_MAX   4096
#define QPU_RESULT_MAX 2048

enum qpu_job_status {
	QPU_JOB_PENDING = 0,
	QPU_JOB_RUNNING = 1,
	QPU_JOB_DONE    = 2,
	QPU_JOB_FAILED  = 3,
};

struct qpu_submit {
	__u64 job_id;             /* out: assigned by the kernel */
	__u32 num_qubits;         /* in */
	__u32 shots;               /* in */
	__u32 qasm_len;             /* in: bytes of qasm[] actually used */
	char  qasm[QPU_QASM_MAX];    /* in */
} __attribute__((packed));

struct qpu_query {
	__u64 job_id;                /* in */
	__u32 status;                 /* out: see enum qpu_job_status */
	__u32 result_len;              /* out: bytes of result[] valid */
	char  result[QPU_RESULT_MAX];   /* out: only valid if DONE/FAILED */
} __attribute__((packed));

struct qpu_fetch {
	__u64 job_id;                 /* out */
	__u32 num_qubits;              /* out */
	__u32 shots;                    /* out */
	__u32 qasm_len;                  /* out */
	char  qasm[QPU_QASM_MAX];         /* out */
} __attribute__((packed));

struct qpu_complete {
	__u64 job_id;                  /* in */
	__u32 ok;                       /* in: 1 = success, 0 = error */
	__u32 result_len;                /* in */
	char  result[QPU_RESULT_MAX];      /* in: JSON counts, or an error message */
} __attribute__((packed));

#define QPU_IOC_MAGIC 'q'

#define QPU_IOC_SUBMIT   _IOWR(QPU_IOC_MAGIC, 1, struct qpu_submit)
#define QPU_IOC_QUERY    _IOWR(QPU_IOC_MAGIC, 2, struct qpu_query)
#define QPU_IOC_FETCH    _IOWR(QPU_IOC_MAGIC, 3, struct qpu_fetch)
#define QPU_IOC_COMPLETE _IOWR(QPU_IOC_MAGIC, 4, struct qpu_complete)

#endif /* QPU_IOCTL_H */
