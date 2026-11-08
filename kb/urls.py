from django.urls import path

from . import views

app_name = "kb"

urlpatterns = [
    path("", views.home, name="home"),
]
