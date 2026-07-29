obj-m += qpu_driver.o
KDIR ?= /root/WSL2-Linux-Kernel

all:
	$(MAKE) -C $(KDIR) M=$(shell pwd) modules

clean:
	$(MAKE) -C $(KDIR) M=$(shell pwd) clean
