"""Paid enrolment, student profile, locations and the map endpoints."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from accounts.models import User
from payments import mpesa
from payments.models import Payment

from .models import Course, Department, Enrollment, Student, Teacher

PW = 'pw-Strong-123'
MPESA = dict(
    MPESA_ENV='sandbox', MPESA_CONSUMER_KEY='k', MPESA_CONSUMER_SECRET='s', MPESA_SHORTCODE='174379',
    MPESA_PASSKEY='p', MPESA_CALLBACK_SECRET='sec', MPESA_CALLBACK_BASE_URL='https://example.ngrok.app',
)
CALLBACK = '/api/payments/mpesa/callback/sec/'


def stk_ok(checkout='ws_CO_E1'):
    return {'MerchantRequestID': 'mr', 'CheckoutRequestID': checkout, 'ResponseCode': '0'}


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk('admin@x.com', PW, role='admin')
        cls.editor = mk('editor@x.com', PW, role='editor')
        cls.teacher_user = mk('teacher@x.com', PW, role='teacher')
        cls.reader = mk('reader@x.com', PW, role='reader', first_name='Rita')
        cls.author = mk('author@x.com', PW, role='author')
        cls.dept = Department.objects.create(name='Science')
        cls.teacher = Teacher.objects.create(first_name='T', last_name='One', email='t1@s.com',
                                             department=cls.dept, user=cls.teacher_user)
        cls.paid = Course.objects.create(name='Paid Course', code='P1', department=cls.dept, fee=5000)
        cls.free = Course.objects.create(name='Free Course', code='F1', department=cls.dept, fee=0)

    def setUp(self):
        cache.clear()

    def as_(self, user):
        self.client.force_authenticate(user)

    def callback(self, code=0, amount=5000, checkout='ws_CO_E1'):
        cb = {'MerchantRequestID': 'mr', 'CheckoutRequestID': checkout, 'ResultCode': code, 'ResultDesc': 'x'}
        if code == 0:
            cb['CallbackMetadata'] = {'Item': [{'Name': 'Amount', 'Value': amount}, {'Name': 'MpesaReceiptNumber', 'Value': 'RCPT1'}]}
        self.client.force_authenticate(None)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(CALLBACK, {'Body': {'stkCallback': cb}}, format='json')


@override_settings(**MPESA)
class EnrollTests(Base):
    def test_requires_login(self):
        self.assertEqual(self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json').status_code, 401)

    def test_free_course_activates_immediately_and_promotes_a_reader_to_student(self):
        self.as_(self.reader)
        res = self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()['enrollment']['status'], 'active')
        self.assertIsNone(res.json()['payment'])
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.role, 'student')
        student = Student.objects.get(user=self.reader)
        self.assertEqual(student.admission_number, f'WEB-{self.reader.pk:06d}')
        self.assertEqual(student.first_name, 'Rita')

    def test_staff_roles_are_not_demoted_or_changed_by_enrolling(self):
        self.as_(self.author)
        self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, 'author')

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_paid_course_returns_202_then_callback_activates(self, push):
        self.as_(self.reader)
        res = self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {'phone': '0712 345 678'}, format='json')
        self.assertEqual(res.status_code, 202, res.content)
        body = res.json()
        self.assertEqual(body['enrollment']['status'], 'pending')
        self.assertEqual((body['payment']['amount'], body['payment']['purpose'], body['payment']['status']),
                         (5000, 'enrollment', 'pending'))
        payment = Payment.objects.get()
        self.assertEqual((payment.phone, payment.account_reference), ('254712345678', f"ENR-{body['enrollment']['id']}"))

        self.assertEqual(self.callback().status_code, 200)
        enrollment = Enrollment.objects.get()
        self.assertEqual(enrollment.status, 'active')
        self.assertEqual((enrollment.amount_paid, enrollment.payment), (Decimal('5000'), payment))
        self.assertEqual(Student.objects.get().phone, '254712345678')

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_cancelled_prompt_keeps_enrollment_pending_and_retryable(self, push):
        self.as_(self.reader)
        self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {'phone': '0712345678'}, format='json')
        self.callback(code=1032)
        self.assertEqual(Enrollment.objects.get().status, 'pending')
        self.as_(self.reader)
        # second attempt reuses the remembered number and a fresh prompt (new checkout id)
        with mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok('ws_CO_E2')):
            res = self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {}, format='json')
        self.assertEqual(res.status_code, 202)
        self.assertEqual(Payment.objects.count(), 2)

    def test_callback_before_the_link_is_saved_still_activates(self):
        self.as_(self.reader)
        from . import services
        enrollment, _ = services.start_enrollment(self.reader, self.paid)
        Payment.objects.create(user=self.reader, phone='254712345678', amount=5000, purpose='enrollment',
                               account_reference=f'ENR-{enrollment.pk}', checkout_request_id='ws_CO_E1')
        self.callback()
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, 'active')

    def test_phone_is_required_for_a_paid_course_when_none_is_stored(self):
        self.as_(self.reader)
        res = self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('phone', res.json())
        self.assertEqual(Payment.objects.count(), 0)

    def test_bad_phone_is_a_400_with_a_message(self):
        self.as_(self.reader)
        res = self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {'phone': '123'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('valid Safaricom number', res.json()['detail'])

    @mock.patch('payments.services.mpesa.stk_push', side_effect=mpesa.MpesaError('M-Pesa is down'))
    def test_daraja_outage_keeps_enrollment_pending(self, push):
        self.as_(self.reader)
        res = self.client.post(f'/api/courses/{self.paid.pk}/enroll/', {'phone': '0712345678'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('M-Pesa is down', res.json()['detail'])
        self.assertEqual(Enrollment.objects.get().status, 'pending')

    def test_cannot_enroll_twice_or_in_a_full_course(self):
        self.as_(self.reader)
        self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        res = self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('already enrolled', res.json()['detail'])

        Course.objects.filter(pk=self.free.pk).update(capacity=1)
        self.as_(self.author)
        res = self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('full', res.json()['detail'])

    def test_enroll_attempts_are_rate_limited(self):
        self.as_(self.reader)
        self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        for _ in range(19):
            self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json')
        self.assertEqual(self.client.post(f'/api/courses/{self.free.pk}/enroll/', {}, format='json').status_code, 429)


@override_settings(**MPESA)
class CancelAndVisibilityTests(Base):
    def setUp(self):
        super().setUp()
        from . import services
        self.mine, _ = services.start_enrollment(self.reader, self.paid)   # pending

    def test_owner_can_cancel_a_pending_enrollment(self):
        self.as_(self.reader)    # promoted to student by the enrolment above
        res = self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'cancelled')

    def test_others_cannot_see_or_cancel_it(self):
        other = User.objects.create_user('o@x.com', PW, role='student')
        for user in (other, self.author):   # a student, and a role that can't normally read enrollments
            self.as_(user)
            self.assertEqual(self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/').status_code, 404)
        self.as_(self.teacher_user)         # teaches no course the enrollment belongs to
        self.assertEqual(self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/').status_code, 404)

    def test_teacher_of_the_course_still_cannot_cancel_someone_elses_enrollment(self):
        self.paid.teachers.add(self.teacher)
        self.as_(self.teacher_user)
        self.assertEqual(self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/').status_code, 403)

    def test_manager_can_cancel_anyones(self):
        self.as_(self.editor)
        self.assertEqual(self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/').status_code, 200)

    def test_active_enrollment_cannot_be_cancelled(self):
        Enrollment.objects.filter(pk=self.mine.pk).update(status='active')
        self.as_(self.reader)
        res = self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/')
        self.assertEqual(res.status_code, 409)

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_cannot_cancel_while_a_prompt_is_in_flight(self, push):
        from . import services
        services.pay_for_enrollment(Enrollment.objects.get(pk=self.mine.pk), '0712345678')
        self.as_(self.reader)
        self.assertEqual(self.client.post(f'/api/enrollments/{self.mine.pk}/cancel/').status_code, 409)

    def test_student_lists_only_their_own_enrollments(self):
        other = User.objects.create_user('o2@x.com', PW, role='student')
        from . import services
        services.start_enrollment(other, self.free)
        self.as_(self.reader)
        ids = [e['id'] for e in self.client.get('/api/enrollments/').json()['results']]
        self.assertEqual(ids, [self.mine.pk])

    def test_a_reader_still_cannot_list_enrollments(self):
        reader2 = User.objects.create_user('r2@x.com', PW, role='reader')
        self.as_(reader2)
        self.assertEqual(self.client.get('/api/enrollments/').status_code, 403)

    def test_manager_created_enrollments_are_active_and_unique(self):
        student = Student.objects.create(first_name='S', last_name='X', email='sx@s.com', admission_number='A9')
        self.as_(self.editor)
        res = self.client.post('/api/enrollments/', {'student': student.pk, 'course': self.free.pk}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()['status'], 'active')
        dup = self.client.post('/api/enrollments/', {'student': student.pk, 'course': self.free.pk}, format='json')
        self.assertEqual(dup.status_code, 400)

    def test_status_and_payment_fields_are_read_only_in_the_api(self):
        student = Student.objects.create(first_name='S', last_name='Y', email='sy@s.com', admission_number='A8')
        self.as_(self.editor)
        res = self.client.post('/api/enrollments/', {'student': student.pk, 'course': self.free.pk,
                                                     'status': 'pending', 'amount_paid': 99999}, format='json')
        self.assertEqual(res.json()['status'], 'active')
        self.assertEqual(res.json()['amount_paid'], '0')


class CourseApiTests(Base):
    def test_course_exposes_fee_seats_and_my_enrollment(self):
        Course.objects.filter(pk=self.paid.pk).update(capacity=3)
        from . import services
        services.start_enrollment(self.reader, self.free)
        self.as_(self.reader)
        by_code = {c['code']: c for c in self.client.get('/api/courses/').json()['results']}
        self.assertEqual(by_code['P1']['fee'], '5000')
        self.assertEqual((by_code['P1']['seats_left'], by_code['P1']['is_full']), (3, False))
        self.assertIsNone(by_code['P1']['my_enrollment'])
        self.assertEqual(by_code['F1']['my_enrollment']['status'], 'active')
        self.assertEqual(by_code['F1']['my_enrollment']['id'], Enrollment.objects.get().pk)

    def test_listing_courses_does_not_query_per_course(self):
        for i in range(8):
            Course.objects.create(name=f'C{i}', code=f'X{i}', department=self.dept, capacity=5)
        self.as_(self.reader)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/api/courses/')
        self.assertLess(len(ctx), 12, [q['sql'][:80] for q in ctx.captured_queries])

    def test_managers_set_venue_and_pin_but_not_half_a_pin(self):
        self.as_(self.editor)
        ok = self.client.patch(f'/api/courses/{self.paid.pk}/', {
            'venue_name': 'Room 4', 'address': 'Nairobi CBD', 'latitude': '-1.286389',
            'longitude': '36.817223', 'place_id': 'abc', 'fee': 7500, 'capacity': 20, 'description': 'Hello',
        }, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual((ok.json()['latitude'], ok.json()['fee'], ok.json()['capacity']), ('-1.286389', '7500', 20))
        half = self.client.patch(f'/api/courses/{self.paid.pk}/', {'latitude': '-1.2', 'longitude': None}, format='json')
        self.assertEqual(half.status_code, 400)
        bad = self.client.patch(f'/api/courses/{self.paid.pk}/', {'latitude': '95', 'longitude': '10'}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_only_managers_can_change_fees(self):
        for user in (self.reader, self.teacher_user, self.author):
            self.as_(user)
            self.assertEqual(self.client.patch(f'/api/courses/{self.paid.pk}/', {'fee': 1}, format='json').status_code, 403)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.fee, 5000)


class StudentProfileTests(Base):
    def test_get_returns_a_blank_profile_without_creating_one(self):
        self.as_(self.reader)
        res = self.client.get('/api/me/student/')
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()['id'])
        self.assertEqual(res.json()['email'], 'reader@x.com')
        self.assertEqual(Student.objects.count(), 0)

    def test_patch_creates_and_saves_phone_and_pin(self):
        self.as_(self.reader)
        res = self.client.patch('/api/me/student/', {
            'phone': '0712 345 678', 'address': 'Westlands', 'latitude': '-1.267', 'longitude': '36.811',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        student = Student.objects.get(user=self.reader)
        self.assertEqual((student.phone, student.address), ('254712345678', 'Westlands'))
        self.assertEqual(self.client.get('/api/me/student/').json()['phone'], '254712345678')

    def test_validation(self):
        self.as_(self.reader)
        self.assertEqual(self.client.patch('/api/me/student/', {'phone': '123'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/me/student/', {'latitude': '1.0'}, format='json').status_code, 400)

    def test_cannot_change_email_or_link_to_other_users(self):
        self.as_(self.reader)
        res = self.client.patch('/api/me/student/', {'email': 'hijack@x.com', 'user': self.admin.pk, 'admission_number': 'X'}, format='json')
        self.assertEqual(res.status_code, 200)
        student = Student.objects.get(user=self.reader)
        self.assertEqual(student.email, 'reader@x.com')
        self.assertEqual(student.user, self.reader)

    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/me/student/').status_code, 401)


class PrivacyAndMapsTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.student_user = User.objects.create_user('stu@x.com', PW, role='student')
        cls.pinned = Student.objects.create(
            first_name='Pinned', last_name='Pete', email='pete@x.com', admission_number='A1', user=cls.student_user,
            address='Kilimani', latitude=Decimal('-1.29'), longitude=Decimal('36.78'), phone='254711111111',
        )
        Student.objects.create(first_name='No', last_name='Pin', email='np@x.com', admission_number='A2')
        cls.shown = Teacher.objects.create(
            first_name='Shown', last_name='Teacher', email='shown@s.com', department=cls.dept,
            address='Westlands', latitude=Decimal('-1.267'), longitude=Decimal('36.811'),
        )
        Teacher.objects.create(first_name='Hidden', last_name='Teacher', email='hid@s.com', department=cls.dept,
                               latitude=Decimal('-1.3'), longitude=Decimal('36.9'), show_on_map=False)

    def student_row(self, user):
        self.as_(user)
        rows = self.client.get('/api/students/').json()['results']
        return next(r for r in rows if r['email'] == 'pete@x.com')

    def test_a_students_address_is_visible_to_managers_and_themselves_only(self):
        self.assertIn('latitude', self.student_row(self.editor))
        self.assertIn('address', self.student_row(self.student_user))
        teacher_view = self.student_row(self.teacher_user)
        for private in ('address', 'latitude', 'longitude', 'place_id'):
            self.assertNotIn(private, teacher_view)
        self.assertEqual(teacher_view['first_name'], 'Pinned')

    def test_teacher_map_is_for_everyone_signed_in_and_respects_opt_out(self):
        self.assertEqual(self.client.get('/api/maps/teachers/').status_code, 401)
        self.as_(self.reader)
        points = self.client.get('/api/maps/teachers/').json()
        self.assertEqual([p['name'] for p in points], ['Shown Teacher'])
        self.assertNotIn('email', points[0])
        self.assertEqual(points[0]['subtitle'], 'Science')

    def test_student_map_is_managers_only(self):
        self.assertEqual(self.client.get('/api/maps/students/').status_code, 401)
        for user in (self.reader, self.teacher_user, self.student_user, self.author):
            self.as_(user)
            self.assertEqual(self.client.get('/api/maps/students/').status_code, 403, user.role)
        for user in (self.editor, self.admin):
            self.as_(user)
            data = self.client.get('/api/maps/students/').json()
            self.assertEqual([p['name'] for p in data['points']], ['Pinned Pete'])
            self.assertEqual(data['total'], 2)

    @override_settings(GOOGLE_MAPS_API_KEY='AIza-test', GOOGLE_MAPS_MAP_ID='MAP1', SCHOOL_NAME='Test School',
                       SCHOOL_LAT=-1.5, SCHOOL_LNG=36.5)
    def test_school_info_serves_the_map_key_to_signed_in_users_only(self):
        self.assertEqual(self.client.get('/api/school/info/').status_code, 401)
        self.as_(self.reader)
        data = self.client.get('/api/school/info/').json()
        self.assertEqual(data['maps'], {'api_key': 'AIza-test', 'map_id': 'MAP1'})
        self.assertEqual((data['school']['name'], data['school']['latitude']), ('Test School', -1.5))

    def test_teachers_can_be_pinned_by_managers_only(self):
        self.as_(self.editor)
        res = self.client.patch(f'/api/teachers/{self.shown.pk}/', {'latitude': '-1.0', 'longitude': '36.0', 'show_on_map': False}, format='json')
        self.assertEqual(res.status_code, 200)
        self.shown.refresh_from_db()
        self.assertFalse(self.shown.show_on_map)
        self.as_(self.teacher_user)
        self.assertEqual(self.client.patch(f'/api/teachers/{self.shown.pk}/', {'latitude': '0'}, format='json').status_code, 403)
