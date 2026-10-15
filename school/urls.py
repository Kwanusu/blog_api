from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    DepartmentViewSet,
    TeacherViewSet,
    StudentViewSet,
    CourseViewSet,
    EnrollmentViewSet,
    SchoolInfoView,
    StudentMapView,
    StudentProfileView,
    TeacherMapView,
)

router = DefaultRouter()

router.register('departments', DepartmentViewSet, basename='department')
router.register('teachers', TeacherViewSet, basename='teacher')
router.register('students', StudentViewSet, basename='student')
router.register('courses', CourseViewSet, basename='course')
router.register('enrollments', EnrollmentViewSet, basename='enrollment')

urlpatterns = [
    path('me/student/', StudentProfileView.as_view(), name='my-student-profile'),
    path('school/info/', SchoolInfoView.as_view(), name='school-info'),
    path('maps/teachers/', TeacherMapView.as_view(), name='map-teachers'),
    path('maps/students/', StudentMapView.as_view(), name='map-students'),
] + router.urls
