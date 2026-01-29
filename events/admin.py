from django.contrib import admin
from .models import Event, EventRegistration, EligibilityCheckRequest

admin.site.register(Event)
admin.site.register(EventRegistration)
from django.conf import settings
from chat_project.utils import send_zeptomail

@admin.register(EligibilityCheckRequest)
class EligibilityCheckRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'status', 'created_at', 'actions_column')
    list_filter = ('status', 'event')
    actions = ['approve_requests', 'reject_requests']

    def actions_column(self, obj):
        from django.utils.html import format_html
        from django.urls import reverse
        
        approve_url = reverse('admin:eligibility-approve', args=[obj.pk])
        reject_url = reverse('admin:eligibility-reject', args=[obj.pk])
        
        buttons = []
        if obj.status == 'pending':
             buttons.append(f'<a class="button" href="{approve_url}" style="margin-right: 5px; background-color: #4ade80; color: white;">Accept</a>')
             buttons.append(f'<a class="button" href="{reject_url}" style="background-color: #f87171; color: white;">Reject</a>')
             
        return format_html(''.join(buttons))
    actions_column.short_description = 'Quick Actions'
    actions_column.allow_tags = True

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('approve/<int:pk>/', self.admin_site.admin_view(self.approve_view), name='eligibility-approve'),
            path('reject/<int:pk>/', self.admin_site.admin_view(self.reject_view), name='eligibility-reject'),
        ]
        return custom_urls + urls

    def approve_view(self, request, pk):
        from django.shortcuts import get_object_or_404, redirect
        obj = get_object_or_404(EligibilityCheckRequest, pk=pk)
        self.approve_requests(request, [obj]) # Reuse existing logic
        return redirect(request.META.get('HTTP_REFERER', 'admin:events_eligibilitycheckrequest_changelist'))

    def reject_view(self, request, pk):
        from django.shortcuts import get_object_or_404, redirect
        obj = get_object_or_404(EligibilityCheckRequest, pk=pk)
        self.reject_requests(request, [obj]) # Reuse existing logic
        return redirect(request.META.get('HTTP_REFERER', 'admin:events_eligibilitycheckrequest_changelist'))

    def approve_requests(self, request, queryset):
        for req in queryset:
            if req.status != 'approved':
                req.status = 'approved'
                req.save()
                
                # Create Registration
                EventRegistration.objects.get_or_create(
                    user=req.user,
                    event=req.event,
                    defaults={'game_username': req.user.username}
                )
                
                # Send Email
                event_link = f"{settings.MAIN_WEBSITE_URL}/events/{req.event.id}"
                subject = "Eligibility Approved - You are Registered!"
                message = f"""
                <html>
                    <body>
                        <p>Hello {req.user.username},</p>
                        <p>Good news! Your eligibility check for <strong>{req.event.title}</strong> has been approved.</p>
                        <p>You have been automatically registered for the event.</p>
                        <p><a href="{event_link}" style="padding: 10px 20px; background-color: #ffd700; color: #000; text-decoration: none; border-radius: 5px;">Go to Event Page</a></p>
                    </body>
                </html>
                """
                try:
                    send_zeptomail(req.user.email, subject, message)
                except Exception as e:
                    self.message_user(request, f"Failed to send email to {req.user.email}: {str(e)}", level='ERROR')
                
        self.message_user(request, "Selected requests have been approved.")
    approve_requests.short_description = "Approve selected requests"

    def reject_requests(self, request, queryset):
        for req in queryset:
            if req.status != 'rejected':
                req.status = 'rejected'
                req.save()
                
                # Send Email
                event_link = f"{settings.MAIN_WEBSITE_URL}/events/{req.event.id}"
                subject = "Eligibility Check Update"
                message = f"""
                <html>
                    <body>
                        <p>Hello {req.user.username},</p>
                        <p>Regarding your eligibility check for <strong>{req.event.title}</strong>.</p>
                        <p>Unfortunately, you do not meet the eligibility criteria at this time.</p>
                        <p>Please review the requirements and you may try again later.</p>
                        <p><a href="{event_link}" style="padding: 10px 20px; background-color: #ffd700; color: #000; text-decoration: none; border-radius: 5px;">Go to Event Page</a></p>
                    </body>
                </html>
                """
                try:
                    send_zeptomail(req.user.email, subject, message)
                except Exception as e:
                    self.message_user(request, f"Failed to send email to {req.user.email}: {str(e)}", level='ERROR')

        self.message_user(request, "Selected requests have been rejected.")
    reject_requests.short_description = "Reject selected requests"
