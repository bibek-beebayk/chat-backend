from rest_framework import serializers
from .models import Blog, BlogComment


class BlogSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'excerpt',
            'meta_title',
            'meta_description',
            'content',
            'cover_image',
            'og_image',
            'author_username',
            'published_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class BlogCommentSerializer(serializers.ModelSerializer):
    can_delete = serializers.SerializerMethodField()

    def get_can_delete(self, obj):
        visitor_hash = self.context.get('visitor_hash')
        return bool(visitor_hash and obj.visitor_hash == visitor_hash)

    class Meta:
        model = BlogComment
        fields = [
            'id',
            'display_name',
            'content',
            'can_delete',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
