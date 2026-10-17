from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import User

Role = User.Role


def has_role(user, *roles):
    return bool(user and user.is_authenticated and user.role in roles)


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return has_role(request.user, Role.ADMIN)


class IsEditorOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return has_role(request.user, Role.ADMIN, Role.EDITOR)


class IsWriter(BasePermission):
    """Admins, editors and authors: everyone who can publish or earn from blog posts.

    Moved here from ``blogs/views.py`` so every permission class lives in one place.
    """

    def has_permission(self, request, view):
        return has_role(request.user, Role.ADMIN, Role.EDITOR, Role.AUTHOR)


class ReadOnlyOrEditor(BasePermission):
    """Any authenticated user may read; only editors and admins may write."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_role(request.user, Role.ADMIN, Role.EDITOR)


class BlogPermission(BasePermission):
    """
    reader : read only
    author : read, create, and edit their own blogs
    editor : read, create, and edit any blog
    admin  : everything, including delete
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == 'POST':
            return has_role(user, Role.ADMIN, Role.EDITOR, Role.AUTHOR)
        if request.method == 'DELETE':
            return has_role(user, Role.ADMIN)
        # PUT / PATCH: object-level check decides for authors.
        return has_role(user, Role.ADMIN, Role.EDITOR, Role.AUTHOR)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if has_role(user, Role.ADMIN, Role.EDITOR):
            return request.method != 'DELETE' or user.role == Role.ADMIN
        if user.role == Role.AUTHOR and request.method != 'DELETE':
            return obj.author.user_id == user.id
        return False
