from django.contrib import admin
from django.utils import timezone
from .models import FAQ


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = (
        'question',
        'category',
        'audience',
        'sort_order',
        'is_featured',
        'is_published',
        'published_at',
        'updated_at',
    )
    list_filter = ('category', 'audience', 'is_featured', 'is_published')
    search_fields = ('question', 'answer')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'published_at'
    ordering = ('sort_order', 'category', 'question')
    actions = ('publish_faqs', 'unpublish_faqs', 'feature_faqs', 'unfeature_faqs')
    fieldsets = (
        ('Content', {
            'fields': ('question', 'answer'),
        }),
        ('Organization', {
            'fields': ('category', 'audience', 'sort_order', 'is_featured'),
        }),
        ('Publishing', {
            'fields': ('is_published', 'published_at', 'created_by'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user
        if obj.is_published and obj.published_at is None:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description='Publish selected FAQs')
    def publish_faqs(self, request, queryset):
        queryset.update(is_published=True, published_at=timezone.now())

    @admin.action(description='Unpublish selected FAQs')
    def unpublish_faqs(self, request, queryset):
        queryset.update(is_published=False)

    @admin.action(description='Feature selected FAQs')
    def feature_faqs(self, request, queryset):
        queryset.update(is_featured=True)

    @admin.action(description='Unfeature selected FAQs')
    def unfeature_faqs(self, request, queryset):
        queryset.update(is_featured=False)
