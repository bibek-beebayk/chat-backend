from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    User,
    EmailVerificationOTP,
    EmailChangeOTP,
    VerificationRequest,
    AppVersion,
    HomeInfoSection,
    HomeInfoPoint,
)

@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = ['version_code', 'is_active', 'is_mandatory', 'created_at']
    list_filter = ['is_active', 'is_mandatory']
    search_fields = ['version_code']


class HomeInfoPointInline(admin.TabularInline):
    model = HomeInfoPoint
    extra = 1
    fields = ['sort_order', 'icon', 'content']
    ordering = ['sort_order', 'id']


@admin.register(HomeInfoSection)
class HomeInfoSectionAdmin(admin.ModelAdmin):
    list_display = ['user_type', 'title', 'is_active', 'updated_at']
    list_filter = ['user_type', 'is_active']
    search_fields = ['title', 'subtitle', 'footer', 'points__content', 'points__icon']
    ordering = ['user_type']
    inlines = [HomeInfoPointInline]

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'user_type', 'agent_availability', 'is_test_user', 'is_active', 'is_verified', 'external_user_id', 'is_staff']
    list_filter = ['user_type', 'agent_availability', 'is_test_user', 'is_active', 'is_verified', 'is_staff']
    search_fields = ['username', 'email', 'external_user_id']
    # readonly_fields = ['external_user_id']
    ordering = ['-date_joined']
    actions = ['export_users_to_csv']

    def export_users_to_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse
        from django.shortcuts import render

        # Define the available fields
        available_fields = [
            ('id', 'ID'),
            ('username', 'Username'),
            ('email', 'Email'),
            ('user_type', 'User Type'),
            ('external_user_id', 'External ID'),
            ('is_verified', 'Is Verified'),
            ('is_active', 'Is Active'),
            ('date_joined', 'Date Joined'),
        ]

        if 'apply_export' in request.POST:
            selected_field_names = request.POST.getlist('export_fields')
            
            # Create a dictionary for quick lookup of field labels
            field_dict = dict(available_fields)
            
            # Filter selected fields to only those that are valid
            valid_fields = [f for f in selected_field_names if f in field_dict]
            
            if not valid_fields:
                self.message_user(request, "No fields selected for export.", level='WARNING')
                return None
                
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="users_export.csv"'

            writer = csv.writer(response)
            
            # Write headers
            headers = [field_dict[f] for f in valid_fields]
            writer.writerow(headers)

            for user in queryset:
                row = []
                for field_name in valid_fields:
                    if field_name == 'user_type':
                        row.append(user.get_user_type_display())
                    elif field_name == 'date_joined':
                        row.append(user.date_joined.strftime('%Y-%m-%d %H:%M:%S') if user.date_joined else '')
                    else:
                        row.append(getattr(user, field_name, ''))
                writer.writerow(row)
                
            return response
            
        context = {
            **self.admin_site.each_context(request),
            'title': 'Export Users to CSV',
            'queryset': queryset,
            'export_fields': available_fields,
        }
        return render(request, "admin/accounts/user/export_users_intermediate.html", context)
    export_users_to_csv.short_description = "Export selected users to CSV"

    def save_model(self, request, obj, form, change):
        if obj.pk:
            orig_obj = User.objects.get(pk=obj.pk)
            if obj.password != orig_obj.password:
                obj.set_password(obj.password)
        else:
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)


@admin.register(EmailVerificationOTP)
class EmailVerificationOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp_code', 'created_at', 'expires_at', 'is_used', 'attempts']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'user__email', 'otp_code']
    readonly_fields = ['created_at', 'expires_at']
    ordering = ['-created_at']


@admin.register(EmailChangeOTP)
class EmailChangeOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'new_email', 'otp_code', 'created_at', 'expires_at', 'is_used', 'attempts']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'user__email', 'new_email', 'otp_code']
    readonly_fields = ['created_at', 'expires_at']
    ordering = ['-created_at']


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'get_email', 'external_user_id', 'status_badge', 'created_at', 'reviewed_by', 'action_buttons']
    list_filter = ['status', 'created_at']
    search_fields = ['user__username', 'user__email', 'external_user_id']
    readonly_fields = ['created_at', 'reviewed_at', 'reviewed_by']
    ordering = ['-created_at']
    actions = ['approve_requests', 'reject_requests']
    
    fieldsets = (
        ('Request Information', {
            'fields': ('user', 'external_user_id', 'status')
        }),
        ('Review Information', {
            'fields': ('reviewed_at', 'reviewed_by', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )
    
    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email'
    get_email.admin_order_field = 'user__email'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#fbbf24',  # yellow
            'approved': '#10b981',  # green
            'rejected': '#ef4444',  # red
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#6b7280'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'
    
    def action_buttons(self, obj):
        if obj.status != 'pending':
            return '-'
        return format_html(
            '<a class="button" href="{}">Accept</a>&nbsp;'
            '<a class="button" style="background-color: #ef4444;" href="{}">Reject</a>',
            f"{obj.id}/approve/",
            f"{obj.id}/reject/"
        )
    action_buttons.short_description = 'Actions'
    action_buttons.allow_tags = True
    
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:request_id>/approve/',
                self.admin_site.admin_view(self.approve_view),
                name='verificationrequest_approve',
            ),
            path(
                '<int:request_id>/reject/',
                self.admin_site.admin_view(self.reject_view),
                name='verificationrequest_reject',
            ),
        ]
        return custom_urls + urls

    def approve_view(self, request, request_id):
        from django.shortcuts import redirect, get_object_or_404
        from django.contrib import messages
        
        verification_request = get_object_or_404(VerificationRequest, pk=request_id)
        if verification_request.status == 'pending':
            verification_request.approve(request.user)
            self.message_user(request, f'Request for {verification_request.user} approved.', messages.SUCCESS)
        else:
            self.message_user(request, 'Request already processed.', messages.WARNING)
            
        return redirect('admin:accounts_verificationrequest_changelist')

    def reject_view(self, request, request_id):
        from django.shortcuts import redirect, get_object_or_404
        from django.contrib import messages
        
        verification_request = get_object_or_404(VerificationRequest, pk=request_id)
        if verification_request.status == 'pending':
            verification_request.reject(request.user)
            self.message_user(request, f'Request for {verification_request.user} rejected.', messages.SUCCESS)
        else:
            self.message_user(request, 'Request already processed.', messages.WARNING)
            
        return redirect('admin:accounts_verificationrequest_changelist')

    def approve_requests(self, request, queryset):
        """Approve selected verification requests"""
        approved_count = 0
        for verification_request in queryset.filter(status='pending'):
            verification_request.approve(request.user)
            approved_count += 1
        
        self.message_user(
            request,
            f'{approved_count} verification request(s) approved successfully.'
        )
    approve_requests.short_description = 'Approve selected requests'
    
    def reject_requests(self, request, queryset):
        """Reject selected verification requests"""
        rejected_count = 0
        for verification_request in queryset.filter(status='pending'):
            verification_request.reject(request.user)
            rejected_count += 1
        
        self.message_user(
            request,
            f'{rejected_count} verification request(s) rejected.'
        )
    reject_requests.short_description = 'Reject selected requests'

from .models import PlayerSearch

@admin.register(PlayerSearch)
class PlayerSearchAdmin(admin.ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        return player_search_view(request)

def player_search_view(request):
    from django.shortcuts import render
    import requests
    from django.conf import settings
    
    context = {
        **admin.site.each_context(request),
        'title': 'Search Player',
    }

    if request.method == 'POST':
        username = request.POST.get('username')
        if username:
            context['username'] = username
            try:
                # Backend fetch
                url = f"{settings.PLAYER_DATA_API_BASE_URL}/player/search?username={username}"
                response = requests.get(url, headers={'x-secret-key': settings.PLAYER_DATA_API_KEY})
                
                # We can intercept/modify response here
                data = response.json()

                # print("data", data)
                
                context['result'] = data
                context['status_code'] = response.status_code
                
            except Exception as e:
                context['error'] = str(e)
                
    return render(request, "admin/accounts/player_search.html", context)
