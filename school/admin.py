from django.contrib import admin
from django.db.models import Count, Q

from .models import Course, Department, Enrollment, Student, Teacher

admin.site.register(Department)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'department', 'email', 'show_on_map')
    list_filter = ('department', 'show_on_map')
    search_fields = ('first_name', 'last_name', 'email')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'email', 'phone', 'user')
    search_fields = ('first_name', 'last_name', 'email', 'admission_number', 'phone')
    raw_id_fields = ('user',)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'department', 'fee', 'capacity', 'enrolled', 'start_date')
    list_filter = ('department',)
    search_fields = ('code', 'name', 'venue_name', 'address')
    filter_horizontal = ('teachers',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _enrolled=Count('enrollments', filter=Q(enrollments__status=Enrollment.Status.ACTIVE)),
        )

    @admin.display(description='Enrolled', ordering='_enrolled')
    def enrolled(self, obj):
        return obj._enrolled


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'status', 'amount_paid', 'paid_at', 'grade')
    list_filter = ('status', 'course')
    search_fields = ('student__first_name', 'student__last_name', 'student__email', 'course__name')
    raw_id_fields = ('student', 'course', 'payment')
    readonly_fields = ('payment', 'amount_paid', 'paid_at')
