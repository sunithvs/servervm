from django.contrib.auth.models import User, Group
from home.serializers import GetTokensSerializer
from rest_framework import serializers


# first we define the serializers
class UserSerializer(serializers.ModelSerializer):
    tokens = GetTokensSerializer(many=False, read_only=True, required=False)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', "first_name", "last_name", 'tokens',)


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ("name",)
