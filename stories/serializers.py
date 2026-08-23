from rest_framework import serializers

from accounts.serializers import UserSerializer

from .models import Story


class StorySerializer(serializers.ModelSerializer):
    is_viewed = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = ['id', 'media', 'caption', 'created_at', 'expires_at', 'is_viewed']
        read_only_fields = fields

    def get_is_viewed(self, obj):
        viewed_story_ids = self.context.get('viewed_story_ids')
        if viewed_story_ids is None:
            return False
        return obj.id in viewed_story_ids


class StoryGroupSerializer(serializers.Serializer):
    """
    Not a ModelSerializer - one row per author with >=1 active story,
    synthesized in the view (see stories/views.py::story_list_view) rather
    than coming straight off a single queryset.
    """
    author = UserSerializer(read_only=True)
    stories = StorySerializer(many=True, read_only=True)
    has_unviewed = serializers.BooleanField(read_only=True)
    is_own = serializers.BooleanField(read_only=True)
