"""Expose the selected upload quality to evidence forms."""

from django import template

from apps.config_center.models import SiteConfiguration

register = template.Library()


@register.simple_tag
def image_profile():
    return SiteConfiguration.load().image_quality
