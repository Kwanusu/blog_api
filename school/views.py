from django.conf import settings
from django.db.models import Count, ProtectedError, Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsEditorOrAdmin
from payments.serializers import PaymentSerializer
from payments.services import PaymentError

from . import services
from .models import (
    Department,
    Teacher,
    Student,
    Course,
    Enrollment,
)

from .permissions import EnrollmentPermission, SchoolRolePermission

from .serializers import (
    DepartmentSerializer,
    TeacherSerializer,
    StudentSerializer,
    CourseSerializer,
    EnrollmentSerializer,
    EnrollRequestSerializer,
    StudentProfileSerializer,
)

Role = User.Role

ALL_ROLES = tuple(Role.values)
STAFF_ROLES = (Role.ADMIN, Role.EDITOR, Role.TEACHER)
MANAGER_ROLES = (Role.ADMIN, Role.EDITOR)
ADMIN_ONLY = (Role.ADMIN,)


# Shared by the school list endpoints: ?search=, ?ordering= and exact-match filters (review item C).
# Each view still chooses *which* fields are searchable/filterable, so private data is never exposed.
LIST_FILTER_BACKENDS = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]


class ProtectedDeleteMixin:
    """A PROTECTed delete is a client conflict (409), not a server error (500)."""

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This can't be deleted while other records (teachers or courses) still use it."},
                status=status.HTTP_409_CONFLICT,
            )


class DepartmentViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = Department.objects.all().order_by("name")
    serializer_class = DepartmentSerializer
    filter_backends = LIST_FILTER_BACKENDS
    search_fields = ["name", "description"]
    permission_classes = [SchoolRolePermission]
    read_roles = ALL_ROLES
    write_roles = MANAGER_ROLES
    delete_roles = ADMIN_ONLY


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.select_related(
        "department"
    ).all().order_by("last_name")
    serializer_class = TeacherSerializer
    filter_backends = LIST_FILTER_BACKENDS
    filterset_fields = ["department"]
    search_fields = ["first_name", "last_name", "email"]
    ordering_fields = ["last_name", "first_name"]
    permission_classes = [SchoolRolePermission]
    read_roles = STAFF_ROLES
    write_roles = MANAGER_ROLES
    delete_roles = ADMIN_ONLY


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by("last_name")
    serializer_class = StudentSerializer
    filter_backends = LIST_FILTER_BACKENDS
    # Only non-sensitive columns are searchable: filtering on phone/date of birth would leak them.
    search_fields = ["first_name", "last_name", "admission_number"]
    ordering_fields = ["last_name", "first_name", "admission_number"]
    permission_classes = [SchoolRolePermission]
    read_roles = STAFF_ROLES + (Role.STUDENT,)
    write_roles = MANAGER_ROLES
    delete_roles = ADMIN_ONLY

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role == Role.STUDENT:
            return qs.filter(user=self.request.user)
        return qs


class CourseViewSet(viewsets.ModelViewSet):
    queryset = Course.objects.select_related(
        "department"
    ).prefetch_related("teachers").annotate(
        taken=Count("enrollments", filter=Q(enrollments__status=Enrollment.Status.ACTIVE)),
    ).order_by("code")
    serializer_class = CourseSerializer
    filter_backends = LIST_FILTER_BACKENDS
    filterset_fields = ["department", "teachers"]
    search_fields = ["name", "code", "description", "department__name"]
    ordering_fields = ["code", "name", "start_date", "fee"]
    permission_classes = [SchoolRolePermission]
    read_roles = ALL_ROLES
    write_roles = MANAGER_ROLES
    delete_roles = ADMIN_ONLY
    throttle_scope = None   # set per-action (@action(throttle_scope=...)); DRF needs the attribute to exist

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated:
            context["my_enrollments"] = {
                course_id: {"id": enrollment_id, "status": enrollment_status}
                for course_id, enrollment_id, enrollment_status in
                Enrollment.objects.filter(student__user=user).values_list("course_id", "id", "status")
            }
        return context

    @action(
        detail=True, methods=["post"], permission_classes=[IsAuthenticated],
        throttle_classes=[ScopedRateThrottle], throttle_scope="payments",
    )
    def enroll(self, request, pk=None):
        """
        Enroll the signed-in user. Free course: 201 and active. Paid course: 202 with the payment —
        an M-Pesa prompt has been sent to `phone`; poll /api/payments/<id>/ until it settles.
        """
        course = self.get_object()
        body = EnrollRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            enrollment, needs_payment = services.start_enrollment(request.user, course)
            if not needs_payment:
                return Response(
                    {"enrollment": EnrollmentSerializer(enrollment).data, "payment": None},
                    status=status.HTTP_201_CREATED,
                )
            phone = body.validated_data.get("phone") or enrollment.student.phone
            if not phone:
                raise ValidationError({"phone": "Enter the M-Pesa number to send the payment prompt to."})
            payment = services.pay_for_enrollment(enrollment, phone)
        except services.EnrollmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        enrollment.refresh_from_db()
        return Response(
            {"enrollment": EnrollmentSerializer(enrollment).data, "payment": PaymentSerializer(payment).data},
            status=status.HTTP_202_ACCEPTED,
        )


class EnrollmentViewSet(viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related(
        "student",
        "course",
    ).all().order_by("-enrolled_on")
    serializer_class = EnrollmentSerializer
    filter_backends = LIST_FILTER_BACKENDS
    filterset_fields = ["course", "student", "status"]
    ordering_fields = ["enrolled_on", "grade"]
    permission_classes = [EnrollmentPermission]
    read_roles = STAFF_ROLES + (Role.STUDENT,)
    write_roles = STAFF_ROLES  # teachers: grade updates on own courses only
    delete_roles = ADMIN_ONLY

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in MANAGER_ROLES:
            return qs
        if user.role == Role.TEACHER:
            return qs.filter(course__teachers__user=user).distinct()
        # Everyone else (students, and any role reaching an extra action) only ever sees their own.
        return qs.filter(student__user=user)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def cancel(self, request, pk=None):
        """Cancel your own unpaid enrollment (managers may cancel anyone's)."""
        enrollment = self.get_object()
        if request.user.role not in MANAGER_ROLES and enrollment.student.user_id != request.user.id:
            raise PermissionDenied("You can only cancel your own enrollment.")
        try:
            services.cancel_enrollment(enrollment)
        except services.EnrollmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(enrollment).data)


@extend_schema(request=StudentProfileSerializer, responses=StudentProfileSerializer)
class StudentProfileView(APIView):
    """The signed-in user's own student profile: phone (for M-Pesa) and optional address."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = Student.objects.filter(user=user).first() or Student(
            user=user, email=user.email, first_name=user.first_name, last_name=user.last_name,
        )
        return Response(StudentProfileSerializer(profile).data)

    def patch(self, request):
        profile = Student.for_user(request.user)
        serializer = StudentProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(responses=OpenApiTypes.OBJECT)
class SchoolInfoView(APIView):
    """The school's own details, plus the (public, referrer-restricted) Google Maps browser key."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "school": {
                "name": settings.SCHOOL_NAME,
                "address": settings.SCHOOL_ADDRESS,
                "latitude": settings.SCHOOL_LAT,
                "longitude": settings.SCHOOL_LNG,
                "phone": settings.SCHOOL_PHONE,
                "email": settings.SCHOOL_EMAIL,
            },
            "maps": {
                "api_key": settings.GOOGLE_MAPS_API_KEY,
                "map_id": settings.GOOGLE_MAPS_MAP_ID,
            },
        })


@extend_schema(responses=OpenApiTypes.OBJECT)
class TeacherMapView(APIView):
    """Pins for teachers who opted in. No emails or other personal details."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        teachers = Teacher.objects.filter(show_on_map=True).exclude(latitude=None).exclude(longitude=None)
        return Response([
            {
                "id": t.id,
                "name": str(t),
                "subtitle": t.department.name,
                "address": t.address,
                "latitude": float(t.latitude),
                "longitude": float(t.longitude),
            }
            for t in teachers.select_related("department")
        ])


@extend_schema(responses=OpenApiTypes.OBJECT)
class StudentMapView(APIView):
    """Student addresses are personal data, so managers only."""

    permission_classes = [IsEditorOrAdmin]

    def get(self, request):
        students = Student.objects.exclude(latitude=None).exclude(longitude=None)
        return Response({
            "total": Student.objects.count(),
            "points": [
                {
                    "id": s.id,
                    "name": f"{s.first_name} {s.last_name}".strip(),
                    "subtitle": s.admission_number,
                    "address": s.address,
                    "latitude": float(s.latitude),
                    "longitude": float(s.longitude),
                }
                for s in students
            ],
        })
