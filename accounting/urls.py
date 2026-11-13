from django.urls import path
from . import views
from . import account_views  # Import views from the current app directory
from django.contrib.auth import views as django_auth
from . import auth_views
from . import office_views, invite_views
from . import counterparty_views
from .office_access import office_write_guard

urlpatterns = [
    path('cash/', account_views.account_list, name='cash-account-list'),
    path('cash/add/', account_views.account_add, name='cash-account-add'),
    path('cash/<int:pk>/', account_views.account_detail, name='cash-account-detail'),
    path('cash/<int:pk>/edit/', account_views.account_edit, name='cash-account-edit'),
    path('cash/<int:pk>/opening/', account_views.account_opening, name='cash-account-opening'),
    path('cash/<int:pk>/adjustment/', account_views.account_adjustment, name='cash-account-adjustment'),
    path('categories/', account_views.category_list, name='category-list'),
    path('categories/add/', account_views.category_add, name='category-add'),
    path('categories/<int:pk>/edit/', account_views.category_edit, name='category-edit'),
    path('categories/<int:pk>/retire/', account_views.category_retire, name='category-retire'),
    path('counterparties/', counterparty_views.workspace, name='counterparty-list'),
    path('entity/<int:pk>/archive/', counterparty_views.archive_view, name='archive-entity'),
    path('entity/<int:pk>/restore/', counterparty_views.restore, name='restore-entity'),
    path('office/settings/', office_views.settings_view, name='office-settings'),
    path('office/members/', office_views.members_view, name='office-members'),
    path('office/invitation/<uuid:key>/<str:action>/', office_views.invitation_action, name='office-invitation-action'),
    path('office/member/<int:user_id>/<str:action>/', office_views.member_action, name='office-member-action'),
    path('office/ownership/', office_views.ownership_view, name='office-ownership'),
    path('office/handover/<uuid:key>/', office_views.handover_detail, name='office-handover-detail'),
    path('office/audit/', office_views.audit_view, name='office-audit'),
    path('join/<uuid:key>/<str:token>/', invite_views.token_entry, name='staff-join-token'),
    path('join/<uuid:key>/', invite_views.join, name='staff-join'),
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
    path('transfer/add/', office_write_guard('finance.write')(views.add_transfer_view), name='add-transfer'),









]
