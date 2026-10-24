from django.urls import path
from .views.dashboard.views import *
from .views.role.views import *
from .views.user_access.views import *

urlpatterns = [
    # user_access
    path('user/access/', UserAccessListView.as_view(), name='user_access_list'),
    path('user/access/delete/<int:pk>/', UserAccessDeleteView.as_view(), name='user_access_delete'),
    # dashboard
    path('dashboard/update/', DashboardUpdateView.as_view(), name='dashboard_update'),
    # roles
    path('roles/', RoleListView.as_view(), name='role_list'),
    path('roles/add/', RoleCreateView.as_view(), name='role_create'),
    path('roles/update/<int:pk>/', RoleUpdateView.as_view(), name='role_update'),
    path('roles/delete/<int:pk>/', RoleDeleteView.as_view(), name='role_delete'),
]
