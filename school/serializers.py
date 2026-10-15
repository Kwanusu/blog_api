
from rest_framework import serializers

from blog_api.location import LOCATION_FIELDS, LocationSerializerMixin
from blog_api.serializer_fields import CloudinaryImageField

from .models import (
    Department,
    Teacher,
    Student,
    Course,
    Enrollment,
)

MANAGERS = ("admin", "editor")


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "description"]


class TeacherSerializer(LocationSerializerMixin, serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
    )

    class Meta:
        model = Teacher
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "department",
            "department_name",
            "show_on_map",
            *LOCATION_FIELDS,
        ]


class StudentSerializer(LocationSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "admission_number",
            "date_of_birth",
            "phone",
            *LOCATION_FIELDS,
        ]
        extra_kwargs = {"date_of_birth": {"required": False}}

    # A student's address is personal data: only managers and the student themself get it.
    PRIVATE = ("address", "latitude", "longitude", "place_id")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        allowed = bool(
            user and user.is_authenticated
            and (user.role in MANAGERS or instance.user_id == user.id)
        )
        if not allowed:
            for field in self.PRIVATE:
                data.pop(field, None)
        return data


class CourseSerializer(LocationSerializerMixin, serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
    )

    teacher_names = serializers.SerializerMethodField()
    thumbnail = CloudinaryImageField(required=False, allow_null=True)
    seats_left = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    my_enrollment = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            "id",
            "name",
            "code",
            "thumbnail",
            "description",
            "fee",
            "capacity",
            "seats_left",
            "is_full",
            "start_date",
            "venue_name",
            *LOCATION_FIELDS,
            "department",
            "department_name",
            "teachers",
            "teacher_names",
            "my_enrollment",
        ]

    def get_teacher_names(self, obj):
        return [
            str(teacher)
            for teacher in obj.teachers.all()
        ]

    # The list view annotates the taken-seat count, which avoids one query per course.
    def _taken(self, obj):
        taken = getattr(obj, "taken", None)
        return obj.taken_seats if taken is None else taken

    def get_seats_left(self, obj):
        if obj.capacity is None:
            return None
        return max(obj.capacity - self._taken(obj), 0)

    def get_is_full(self, obj):
        return obj.capacity is not None and self._taken(obj) >= obj.capacity

    def get_my_enrollment(self, obj):
        """The signed-in user's enrollment in this course as {id, status} (or null), supplied by the view."""
        mine = self.context.get("my_enrollments")
        if mine is None:
            return None
        return mine.get(obj.id)


class EnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="student.__str__",
        read_only=True,
    )

    course_name = serializers.CharField(
        source="course.name",
        read_only=True,
    )
    course_fee = serializers.IntegerField(source="course.fee", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "student",
            "student_name",
            "course",
            "course_name",
            "course_fee",
            "enrolled_on",
            "grade",
            "status",
            "amount_paid",
            "paid_at",
            "payment",
        ]
        read_only_fields = ["enrolled_on", "status", "amount_paid", "paid_at", "payment"]

    def validate(self, attrs):
        # Teachers may only change the grade, never reassign student/course.
        request = self.context.get("request")
        if request and request.user.is_authenticated and request.user.role == "teacher":
            extra = set(attrs) - {"grade"}
            if extra:
                raise serializers.ValidationError(
                    "Teachers can only update the grade."
                )
        return attrs


class StudentProfileSerializer(LocationSerializerMixin, serializers.ModelSerializer):
    """What a signed-in person can edit about their own student profile."""

    class Meta:
        model = Student
        fields = ["id", "first_name", "last_name", "email", "phone", *LOCATION_FIELDS]
        read_only_fields = ["id", "email"]

    def validate_phone(self, value):
        from payments import mpesa
        if not value:
            return ""
        try:
            return mpesa.normalize_phone(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class EnrollRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(required=False, allow_blank=True)
