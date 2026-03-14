from rest_framework import serializers
from .models import Blog


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
