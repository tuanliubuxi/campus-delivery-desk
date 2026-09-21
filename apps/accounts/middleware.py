from django.contrib.auth import logout

from apps.accounts.services.leases import InvalidLease, validate_request_lease


class ActiveLoginLeaseMiddleware:
    """Invalidate authenticated sessions whose bound lease was revoked or replaced."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                validate_request_lease(request)
            except InvalidLease:
                logout(request)
        return self.get_response(request)
