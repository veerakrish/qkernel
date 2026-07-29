#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>

static int __init qpu_hello_init(void)
{
	pr_info("qpu_hello: loaded\n");
	return 0;
}

static void __exit qpu_hello_exit(void)
{
	pr_info("qpu_hello: unloaded\n");
}

module_init(qpu_hello_init);
module_exit(qpu_hello_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("qkernel");
MODULE_DESCRIPTION("Smoke test module validating the out-of-tree kernel module build toolchain");
