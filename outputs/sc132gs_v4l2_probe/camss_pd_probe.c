// SPDX-License-Identifier: GPL-2.0
#include <linux/device.h>
#include <linux/clk.h>
#include <linux/module.h>
#include <linux/ioport.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>

static int __init camss_pd_probe_init(void)
{
	static const char *const names[] = { "ife0", "ife1", "ife2", "top" };
	static const char *const clocks[] = {
		"vfe0", "vfe0_axi", "soc_ahb", "cpas_ahb", "camnoc_axi",
		"gcc_camera_axi"
	};
	struct device *camss;
	struct platform_device *pdev;
	struct resource *resource;
	int irq;
	unsigned int i;

	camss = bus_find_device_by_name(&platform_bus_type, NULL, "acb3000.camss");
	if (!camss) {
		pr_err("camss_pd_probe: CAMSS platform device not found\n");
		return -ENODEV;
	}

	for (i = 0; i < ARRAY_SIZE(names); ++i) {
		struct device *domain = dev_pm_domain_attach_by_name(camss, names[i]);

		if (IS_ERR(domain)) {
			pr_err("camss_pd_probe: attach %s failed: %ld\n",
			       names[i], PTR_ERR(domain));
			continue;
		}
		pr_info("camss_pd_probe: attach %s succeeded: %s\n",
			names[i], dev_name(domain));
		dev_pm_domain_detach(domain, true);
	}

	pdev = to_platform_device(camss);
	resource = platform_get_resource_byname(pdev, IORESOURCE_MEM, "vfe0");
	if (resource)
		pr_info("camss_pd_probe: resource vfe0 succeeded: %pa-%pa\n",
			&resource->start, &resource->end);
	else
		pr_err("camss_pd_probe: resource vfe0 failed\n");

	irq = platform_get_irq_byname(pdev, "vfe0");
	if (irq >= 0)
		pr_info("camss_pd_probe: irq vfe0 succeeded: %d\n", irq);
	else
		pr_err("camss_pd_probe: irq vfe0 failed: %d\n", irq);

	for (i = 0; i < ARRAY_SIZE(clocks); ++i) {
		struct clk *clock = clk_get(camss, clocks[i]);

		if (IS_ERR(clock)) {
			pr_err("camss_pd_probe: clock %s failed: %ld\n",
			       clocks[i], PTR_ERR(clock));
			continue;
		}
		pr_info("camss_pd_probe: clock %s succeeded\n", clocks[i]);
		clk_put(clock);
	}

	put_device(camss);
	return 0;
}

static void __exit camss_pd_probe_exit(void)
{
}

module_init(camss_pd_probe_init);
module_exit(camss_pd_probe_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only CAMSS named power-domain attachment probe");
