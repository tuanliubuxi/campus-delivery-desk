"""Read models used to render configuration-center pages."""

from apps.config_center.models import BusinessTypeConfig, CommissionConfig, SiteConfiguration


def configuration_center_data():
    return {
        "site_config": SiteConfiguration.load(),
        "business_configs": BusinessTypeConfig.objects.all(),
        "commissions": CommissionConfig.objects.all(),
    }
