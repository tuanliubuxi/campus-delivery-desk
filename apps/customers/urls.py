from django.urls import path

from apps.customers import views

app_name = "customers"

urlpatterns = [
    path("recorder/customers/", views.customer_list, name="list"),
    path("recorder/customers/new/", views.customer_create, name="create"),
    path("recorder/customers/<int:customer_id>/edit/", views.customer_edit, name="edit"),
    path("recorder/customers/<int:customer_id>/delete/", views.customer_delete, name="delete"),
]
