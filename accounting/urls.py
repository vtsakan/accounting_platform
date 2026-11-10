from django.urls import path
from . import views  # Import views from the current app directory
from django.contrib.auth import views as django_auth
from . import auth_views

urlpatterns = [
    # This line maps the root URL ('') to a function named 'dashboard_view' in views.py
    path('login/', auth_views.StaffLoginView.as_view(), name='login'),
    path('logout/', django_auth.LogoutView.as_view(), name='logout'),
    path('auth/password/reset/', auth_views.StaffPasswordResetView.as_view(), name='password-reset'),
    path('auth/password/reset/done/', django_auth.PasswordResetDoneView.as_view(template_name='accounting/auth/reset_done.html'), name='password-reset-done'),
    path('auth/password/reset/<uidb64>/<token>/', auth_views.StaffPasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('auth/password/complete/', django_auth.PasswordResetCompleteView.as_view(template_name='accounting/auth/reset_complete.html'), name='password-reset-complete'),
    path('auth/mfa/setup/', auth_views.mfa_setup, name='mfa-setup'),
    path('auth/mfa/qr/', auth_views.mfa_qr, name='mfa-qr'),
    path('auth/mfa/verify/', auth_views.mfa_verify, name='mfa-verify'),
    path('auth/mfa/recover/', auth_views.mfa_recover, name='mfa-recover'),
    path('auth/security/', auth_views.security_settings, name='security-settings'),
    path('', views.dashboard_view, name='dashboard'),
    path('transactions/', views.transaction_list_view, name='transaction-list'),
    path('customers/', views.customer_list_view, name='customer-list'),
    path('suppliers/', views.supplier_list_view, name='supplier-list'),
    path('expense/add/', views.add_expense_view, name='add-expense'),
    path('income/add/', views.add_income_view, name='add-income'),
    path('entity/add/', views.add_entity_view, name='add-entity'),
    path('entity/<int:pk>/', views.entity_detail_view, name='entity-detail'),
    path('report/', views.summary_report_view, name='summary-report'),
    path('entity/<int:pk>/edit/', views.edit_entity_view, name='edit-entity'),
    path('agreements/', views.agreement_list_view, name='agreement-list'),
    path('agreement/<int:pk>/', views.agreement_detail_view, name='agreement-detail'),
    path('agreement/add/', views.add_agreement_view, name='add-agreement'),
    path('agreement/<int:pk>/edit/', views.edit_agreement_view, name='edit-agreement'),
    path('transfer/add/', views.add_transfer_view, name='add-transfer'),









]
