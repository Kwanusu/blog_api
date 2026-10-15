from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import User

Role = User.Role


class SchoolRolePermission(BasePermission):
    """
    Views declare which roles may read, write (create/update) and delete:

        read_roles   - GET/HEAD/OPTIONS
        write_roles  - POST/PUT/PATCH
        delete_roles - DELETE
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            roles = view.read_roles
        elif request.method == 'DELETE':
            roles = view.delete_roles
        else:
            roles = view.write_roles
        return user.role in roles


class EnrollmentPermission(SchoolRolePermission):
    """Teachers may update (grade) only enrollments in courses they teach."""

    def has_permission(self, request, view):
        if (
            request.method == 'POST'
            and request.user.is_authenticated
            and request.user.role == Role.TEACHER
        ):
            return False
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role == Role.TEACHER and request.method not in SAFE_METHODS:
            return obj.course.teachers.filter(user_id=user.id).exists()
        return True
