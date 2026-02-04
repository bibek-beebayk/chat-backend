from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.utils import timezone
from django.contrib.admin.views.decorators import staff_member_required
from accounts.models import User
from chat.models import Message
from notifications.models import MessageDelivery
from events.models import EventRegistration
from datetime import datetime

# Create a custom dashboard view
@staff_member_required
def dashboard_view(request):
    # Default to today
    today = timezone.localtime().date()
    start_date = request.GET.get('start_date', today.strftime('%Y-%m-%d'))
    end_date = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
    
    try:
        start_dt = timezone.make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
        end_dt_obj = datetime.strptime(end_date, '%Y-%m-%d')
        end_dt = timezone.make_aware(end_dt_obj.replace(hour=23, minute=59, second=59))
    except ValueError:
        start_dt = timezone.now().replace(hour=0, minute=0, second=0)
        end_dt = timezone.now().replace(hour=23, minute=59, second=59)

    # 1. New Player Registrations
    new_players = User.objects.filter(
        date_joined__range=(start_dt, end_dt), 
        user_type='player'
    ).count()

    # 2. New Agent Registrations
    new_agents = User.objects.filter(
        date_joined__range=(start_dt, end_dt), 
        user_type='agent'
    ).count()

    # 3. Total Messages
    total_messages = Message.objects.filter(
        timestamp__range=(start_dt, end_dt)
    ).count()

    # 4. Total Mail Sent
    total_emails = MessageDelivery.objects.filter(
        channel='email',
        status='sent',
        timestamp__range=(start_dt, end_dt)
    ).count()

    # 5. Total Event Registrations
    total_event_regs = EventRegistration.objects.filter(
        registration_date__range=(start_dt, end_dt)
    ).count()
    
    # Fetch Standard Admin App List to mimic Index page
    app_list = admin.site.get_app_list(request)

    context = {
        **admin.site.each_context(request),
        'title': 'Analytics Dashboard',
        'app_list': app_list,
        'start_date': start_date,
        'end_date': end_date,
        'stats': {
            'new_players': new_players,
            'new_agents': new_agents,
            'total_messages': total_messages,
            'total_emails': total_emails,
            'total_event_regs': total_event_regs,
        }
    }
    
    return render(request, 'admin/analytics_dashboard.html', context)
