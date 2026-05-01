from django.urls import path

from . import views


urlpatterns = [
    path('onboarding/state/', views.onboarding_state_view, name='social-onboarding-state'),
    path('suggestions/agents/', views.suggested_agents_view, name='social-suggested-agents'),
    path('suggestions/players/', views.suggested_players_view, name='social-suggested-players'),
    path('profiles/<int:user_id>/', views.public_profile_view, name='social-profile'),
    path('connections/', views.connection_list_view, name='social-connections'),
    path('connections/create/', views.create_connection_view, name='social-connections-create'),
    path('connections/disconnect/', views.disconnect_connection_view, name='social-connections-disconnect'),
    path('connections/<int:connection_id>/accept/', views.accept_connection_view, name='social-connections-accept'),
    path('connections/<int:connection_id>/reject/', views.reject_connection_view, name='social-connections-reject'),
    path('connections/search/agents/', views.search_agent_connections_view, name='social-connections-search-agents'),
    path('connections/search/players/', views.search_player_connections_view, name='social-connections-search-players'),
]

