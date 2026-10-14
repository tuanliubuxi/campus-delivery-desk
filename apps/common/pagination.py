"""Small shared pagination helper for bounded operational lists."""

from django.core.paginator import Paginator


def paginate(request, items, *, per_page=20, parameter="page"):
    page = Paginator(items, per_page).get_page(request.GET.get(parameter))
    query = request.GET.copy()
    query.pop(parameter, None)
    return page, query.urlencode()
