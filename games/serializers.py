from rest_framework import serializers
from .models import Game


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'thumbnail',
            'is_active',
        ]
        read_only_fields = fields
