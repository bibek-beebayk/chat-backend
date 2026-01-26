from rest_framework import serializers
from .models import Post
from accounts.serializers import UserSerializer

class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = Post
        fields = ['id', 'title', 'content', 'image', 'video', 'author', 'created_at']
        read_only_fields = ['id', 'created_at', 'author']
