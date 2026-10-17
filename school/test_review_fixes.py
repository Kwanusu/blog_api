"""Regression tests for code-review items B3 (seat holds), B5 (student privacy) and related school fixes."""
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from payments.models import Payment

from .models import Course, Department, Enrollment, Student, Teacher
from .services import seats_in_use

PW = 'pw-Strong-123'
MPESA = dict(
    MPESA_ENV='sandbox', MPESA_CONSUMER_KEY='k', MPESA_CONSUMER_SECRET='s', MPESA_SHORTCODE='174379',
    MPESA_PASSKEY='p', MPESA_CALLBACK_SECRET='sec', MPESA_CALLBACK_BASE_URL='https://example.ngrok.app',
)


def stk_ok(checkout):
    return {'MerchantRequestID': 'mr', 'CheckoutRequestID': checkout, 'ResponseCode': '0'}


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk('admin@x.com', PW, role='admin')
        cls.editor = mk('editor@x.com', PW, role='editor')
        cls.teacher_user = mk('teacher@x.com', PW, role='teacher')
        cls.student_user = mk('stud@x.com', PW, role='student')
        cls.alice = mk('alice@x.com', PW)
        cls.bob = mk('bob@x.com', PW)
        cls.dept = Department.objects.create(name='Science')
        cls.teacher = Teacher.objects.create(first_name='T', last_name='One', email='t1@s.com',
                                             department=cls.dept, user=cls.teacher_user)
        cls.student = Student.objects.create(
            first_name='S', last_name='One', email='s1@s.com', admission_number='A1',
            date_of_birth=date(2010, 1, 1), phone='254712345678', address='Secret Street',
            user=cls.student_user)

    def setUp(self):
        cache.clear()


@override_settings(**MPESA)
class SeatHoldTests(Base):
    """The last seat must not be offered to two people who are both about to pay."""

    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(name='Paid', code='P1', department=self.dept, fee=5000, capacity=1)

    def enroll(self, user, checkout):
        self.client.force_authenticate(user)
        with mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok(checkout)):
            return self.client.post(f'/api/courses/{self.course.pk}/enroll/', {'phone': '0712345678'}, format='json')

    def test_a_live_payment_prompt_reserves_the_seat(self):
        self.assertEqual(self.enroll(self.alice, 'ws_A').status_code, 202)
        second = self.enroll(self.bob, 'ws_B')
        self.assertEqual(second.status_code, 409)
        self.assertIn('full', second.json()['detail'])

    def test_the_seat_is_released_when_the_prompt_is_cancelled(self):
        self.enroll(self.alice, 'ws_A')
        Payment.objects.update(status=Payment.Status.CANCELLED)
        self.assertEqual(self.enroll(self.bob, 'ws_B').status_code, 202)

    def test_the_seat_is_released_when_the_prompt_expires(self):
        self.enroll(self.alice, 'ws_A')
        Payment.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(self.enroll(self.bob, 'ws_B').status_code, 202)

    def test_a_student_is_not_blocked_by_their_own_pending_seat(self):
        self.enroll(self.alice, 'ws_A')
        Payment.objects.update(status=Payment.Status.CANCELLED)
        Enrollment.objects.update(status=Enrollment.Status.PENDING)
        self.assertEqual(self.enroll(self.alice, 'ws_A2').status_code, 202)

    def test_seats_in_use_counts_active_plus_live_holds(self):
        self.enroll(self.alice, 'ws_A')
        self.assertEqual(seats_in_use(self.course), 1)
        Enrollment.objects.update(status=Enrollment.Status.ACTIVE)
        self.assertEqual(seats_in_use(self.course), 1)   # counted once, not twice


class StudentPrivacyTests(Base):
    def fetch(self, user):
        self.client.force_authenticate(user)
        return self.client.get(f'/api/students/{self.student.pk}/').json()

    def test_teachers_do_not_see_phone_dob_or_address(self):
        data = self.fetch(self.teacher_user)
        for field in ('phone', 'date_of_birth', 'address'):
            self.assertNotIn(field, data)
        self.assertEqual(data['admission_number'], 'A1')   # still useful to a teacher

    def test_managers_and_the_student_see_everything(self):
        for user in (self.editor, self.admin, self.student_user):
            data = self.fetch(user)
            self.assertEqual(data['phone'], '254712345678', user.email)
            self.assertIn('date_of_birth', data)

    def test_search_cannot_be_used_to_probe_a_hidden_phone_number(self):
        self.client.force_authenticate(self.teacher_user)
        self.assertEqual(self.client.get('/api/students/?search=254712345678').json()['count'], 0)


class TeacherEmailSyncTests(Base):
    def test_changing_a_teachers_email_updates_the_linked_login(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(f'/api/teachers/{self.teacher.pk}/', {'email': 'new@s.com'})
        self.assertEqual(res.status_code, 200, res.content)
        self.teacher_user.refresh_from_db()
        self.assertEqual(self.teacher_user.email, 'new@s.com')

    def test_an_email_already_used_by_another_login_is_rejected_and_nothing_changes(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(f'/api/teachers/{self.teacher.pk}/', {'email': 'ALICE@x.com'})
        self.assertEqual(res.status_code, 400)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.email, 't1@s.com')   # rolled back with the failed login update


class GradeAndFilterTests(Base):
    def setUp(self):
        super().setUp()
        self.c1 = Course.objects.create(name='Algebra', code='MTH1', department=self.dept, fee=100)
        self.c1.teachers.add(self.teacher)
        self.c2 = Course.objects.create(name='Biology', code='SCI1', department=Department.objects.create(name='Life'))
        self.enr = Enrollment.objects.create(student=self.student, course=self.c1)

    def test_grade_must_be_one_of_the_allowed_letters(self):
        self.client.force_authenticate(self.teacher_user)
        url = f'/api/enrollments/{self.enr.pk}/'
        self.assertEqual(self.client.patch(url, {'grade': 'B'}).status_code, 200)
        self.assertEqual(self.client.patch(url, {'grade': 'a+'}).status_code, 400)
        self.assertEqual(self.client.patch(url, {'grade': '10'}).status_code, 400)

    def test_courses_can_be_searched_filtered_and_ordered(self):
        self.client.force_authenticate(self.alice)
        get = lambda q: [c['code'] for c in self.client.get(f'/api/courses/?{q}').json()['results']]  # noqa: E731
        self.assertEqual(get('search=algebra'), ['MTH1'])
        self.assertEqual(get(f'department={self.c2.department_id}'), ['SCI1'])
        self.assertEqual(get('ordering=-code'), ['SCI1', 'MTH1'])

    def test_enrollments_can_be_filtered_by_course(self):
        self.client.force_authenticate(self.editor)
        res = self.client.get(f'/api/enrollments/?course={self.c1.pk}').json()
        self.assertEqual(res['count'], 1)
        self.assertEqual(self.client.get(f'/api/enrollments/?course={self.c2.pk}').json()['count'], 0)
