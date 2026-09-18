from django.urls import path

from core.funeral.views.service_type.views import *
from core.funeral.views.client_service_rate.views import *
from core.funeral.views.client_profile.views import *
from core.funeral.views.service_reception.views import *

urlpatterns = [
    # service_type
    path('service-type/', ServiceTypeListView.as_view(), name='service_type_list'),
    path('service-type/add/', ServiceTypeCreateView.as_view(), name='service_type_create'),
    path('service-type/update/<int:pk>/', ServiceTypeUpdateView.as_view(), name='service_type_update'),
    path('service-type/delete/<int:pk>/', ServiceTypeDeleteView.as_view(), name='service_type_delete'),
    # client_service_rate
    path('service-rate/', ClientServiceRateListView.as_view(), name='client_service_rate_list'),
    path('service-rate/add/', ClientServiceRateCreateView.as_view(), name='client_service_rate_create'),
    path('service-rate/update/<int:pk>/', ClientServiceRateUpdateView.as_view(), name='client_service_rate_update'),
    path('service-rate/delete/<int:pk>/', ClientServiceRateDeleteView.as_view(), name='client_service_rate_delete'),
    # client_profile
    path('client-profile/', FuneralClientProfileListView.as_view(), name='funeral_client_profile_list'),
    path('client-profile/add/', FuneralClientProfileCreateView.as_view(), name='funeral_client_profile_create'),
    path('client-profile/update/<int:pk>/', FuneralClientProfileUpdateView.as_view(), name='funeral_client_profile_update'),
    path('client-profile/delete/<int:pk>/', FuneralClientProfileDeleteView.as_view(), name='funeral_client_profile_delete'),
    # service_reception
    path('service-reception/', ServiceReceptionListView.as_view(), name='service_reception_list'),
    path('service-reception/new/', ServiceReceptionWizardView.as_view(), name='service_reception_wizard'),
    path('service-reception/update/<int:pk>/', ServiceReceptionUpdateView.as_view(), name='service_reception_update'),
    path('service-reception/delete/<int:pk>/', ServiceReceptionDeleteView.as_view(), name='service_reception_delete'),
]
