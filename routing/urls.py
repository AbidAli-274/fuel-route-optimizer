from django.urls import path

from routing.views import RoutePlanView

app_name = "routing"

urlpatterns = [
    path("route-plans/", RoutePlanView.as_view(), name="route-plan"),
]
