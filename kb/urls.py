from django.urls import path

from . import views

app_name = "kb"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search_view, name="search"),
    path("e/<int:pk>/", views.entry_detail, name="entry"),
    path("e/<int:pk>/progress/", views.entry_progress, name="entry_progress"),
    path("browse/", views.browse, name="browse"),
    path("browse/<str:kind>/", views.browse, name="browse_kind"),
    path("learn/", views.learn, name="learn"),
    path("grades/", views.grades_list, name="grades"),
    path("g/<int:pk>/", views.grade_detail, name="grade"),
    path("c/<int:pk>/", views.company_detail, name="company"),
]
