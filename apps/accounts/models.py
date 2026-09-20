from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Stable custom-user migration root; roles and leases arrive in Phase 1."""
