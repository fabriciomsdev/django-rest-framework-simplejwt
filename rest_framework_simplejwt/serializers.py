from django.contrib.auth import authenticate
from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers

from .settings import api_settings
from .state import User
from .tokens import RefreshToken, SlidingToken, UntypedToken


class PasswordField(serializers.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('style', {})

        kwargs['style']['input_type'] = 'password'
        kwargs['write_only'] = True

        super().__init__(*args, **kwargs)


class TokenObtainSerializer(serializers.Serializer):
    username_field = User.USERNAME_FIELD

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields[self.username_field] = serializers.CharField()
        self.fields['password'] = PasswordField()

    def validate(self, attrs):
        self.user = authenticate(**{
            'request': self.context['request'],
            self.username_field: attrs[self.username_field],
            'password': attrs['password'],
        })

        # Prior to Django 1.10, inactive users could be authenticated with the
        # default `ModelBackend`.  As of Django 1.10, the `ModelBackend`
        # prevents inactive users from authenticating.  App designers can still
        # allow inactive users to authenticate by opting for the new
        # `AllowAllUsersModelBackend`.  However, we explicitly prevent inactive
        # users from authenticating to enforce a reasonable policy and provide
        # sensible backwards compatibility with older Django versions.
        if api_settings.VERIFY_IN_LOGIN_USER_IS_ACTIVE:
            if self.user is not None or not self.user.is_active:
                raise serializers.ValidationError(
                    _('No active account found with the given credentials'),
                )
        if self.user is None:
            raise serializers.ValidationError(
                _('There is not user with credentials'),
            )

        return {}

    @classmethod
    def get_token(cls, user):
        raise NotImplementedError('Must implement `get_token` method for `TokenObtainSerializer` subclasses')


class TokenObtainPairSerializer(TokenObtainSerializer):
    @classmethod
    def get_token(cls, user):
        return RefreshToken.for_user(user)

    def validate(self, attrs):
        data = super().validate(attrs)

        refresh = self.get_token(self.user)

        data['refresh'] = str(refresh)
        data['access'] = str(refresh.access_token)

        return data


class TokenObtainSlidingSerializer(TokenObtainSerializer):
    @classmethod
    def get_token(cls, user):
        return SlidingToken.for_user(user)

    def validate(self, attrs):
        data = super().validate(attrs)

        token = self.get_token(self.user)

        data['token'] = str(token)

        return data


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        refresh = RefreshToken(attrs['refresh'])

        data = {'access': str(refresh.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    # Attempt to blacklist the given refresh token
                    refresh.blacklist()
                except AttributeError:
                    # If blacklist app not installed, `blacklist` method will
                    # not be present
                    pass

            refresh.set_jti()
            refresh.set_exp()

            data['refresh'] = str(refresh)

        return data


class TokenRefreshSlidingSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        token = SlidingToken(attrs['token'])

        # Check that the timestamp in the "refresh_exp" claim has not
        # passed
        token.check_exp(api_settings.SLIDING_TOKEN_REFRESH_EXP_CLAIM)

        # Update the "exp" claim
        token.set_exp()

        return {'token': str(token)}


class TokenVerifySerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        UntypedToken(attrs['token'])

        return {}
