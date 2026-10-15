from datetime import date

from rest_framework.test import APITestCase

from accounts.models import User

from .models import Course, Department, Enrollment, Student, Teacher


class SchoolRBACTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        pw = 'pw-Strong-123'
        cls.admin = mk('a@x.com', pw, role=User.Role.ADMIN)
        cls.editor = mk('e@x.com', pw, role=User.Role.EDITOR)
        cls.teacher_u = mk('t1@x.com', pw, role=User.Role.TEACHER)
        cls.teacher2_u = mk('t2@x.com', pw, role=User.Role.TEACHER)
        cls.student_u = mk('s1@x.com', pw, role=User.Role.STUDENT)
        cls.reader = mk('r@x.com', pw)

        cls.dept = Department.objects.create(name='Science')
        cls.teacher = Teacher.objects.create(
            first_name='T', last_name='One', email='t1@s.com',
            department=cls.dept, user=cls.teacher_u)
        cls.teacher2 = Teacher.objects.create(
            first_name='T', last_name='Two', email='t2@s.com',
            department=cls.dept, user=cls.teacher2_u)
        cls.student = Student.objects.create(
            first_name='S', last_name='One', email='s1@s.com',
            admission_number='A1', date_of_birth=date(2010, 1, 1), user=cls.student_u)
        cls.student2 = Student.objects.create(
            first_name='S', last_name='Two', email='s2@s.com',
            admission_number='A2', date_of_birth=date(2010, 1, 2))
        cls.course = Course.objects.create(name='Bio', code='B1', department=cls.dept)
        cls.course.teachers.add(cls.teacher)
        cls.course2 = Course.objects.create(name='Chem', code='C1', department=cls.dept)
        cls.course2.teachers.add(cls.teacher2)
        cls.enr = Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.enr2 = Enrollment.objects.create(student=cls.student2, course=cls.course2)

    def test_anonymous_denied_everywhere(self):
        for path in ('departments', 'teachers', 'students', 'courses', 'enrollments'):
            self.assertEqual(self.client.get(f'/api/{path}/').status_code, 401, path)

    def test_reader_sees_catalog_only(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/courses/').status_code, 200)
        self.assertEqual(self.client.get('/api/departments/').status_code, 200)
        self.assertEqual(self.client.get('/api/students/').status_code, 403)
        self.assertEqual(self.client.get('/api/enrollments/').status_code, 403)
        self.assertEqual(self.client.post('/api/departments/', {'name': 'X'}).status_code, 403)

    def test_student_sees_only_own_data(self):
        self.client.force_authenticate(self.student_u)
        r = self.client.get('/api/students/')
        self.assertEqual([s['id'] for s in r.data['results']], [self.student.id])
        r = self.client.get('/api/enrollments/')
        self.assertEqual([e['id'] for e in r.data['results']], [self.enr.id])
        self.assertEqual(self.client.get(f'/api/enrollments/{self.enr2.id}/').status_code, 404)
        self.assertEqual(
            self.client.patch(f'/api/enrollments/{self.enr.id}/', {'grade': 'A'}).status_code, 403)

    def test_teacher_grades_only_own_courses(self):
        self.client.force_authenticate(self.teacher_u)
        r = self.client.get('/api/enrollments/')
        self.assertEqual([e['id'] for e in r.data['results']], [self.enr.id])
        url = f'/api/enrollments/{self.enr.id}/'
        self.assertEqual(self.client.patch(url, {'grade': 'A'}).status_code, 200)
        self.assertEqual(
            self.client.patch(url, {'course': self.course2.id}).status_code, 400)
        self.assertEqual(
            self.client.patch(f'/api/enrollments/{self.enr2.id}/', {'grade': 'A'}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 403)
        r = self.client.post('/api/enrollments/', {
            'student': self.student2.id, 'course': self.course.id})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post('/api/courses/', {
            'name': 'N', 'code': 'N1', 'department': self.dept.id}).status_code, 403)

    def test_editor_manages_but_cannot_delete(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post('/api/enrollments/', {
            'student': self.student2.id, 'course': self.course.id})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            self.client.delete(f'/api/enrollments/{self.enr.id}/').status_code, 403)

    def test_admin_can_delete(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.delete(f'/api/enrollments/{self.enr.id}/').status_code, 204)


class ProtectedDeleteTests(APITestCase):
    def test_deleting_a_department_in_use_is_a_409_not_a_500(self):
        admin = User.objects.create_user('pd-admin@x.com', 'pw-Strong-123', role=User.Role.ADMIN)
        dept = Department.objects.create(name='Arts')
        Teacher.objects.create(first_name='T', last_name='X', email='tx@s.com', department=dept)
        self.client.force_authenticate(admin)
        r = self.client.delete(f'/api/departments/{dept.id}/')
        self.assertEqual(r.status_code, 409)
        self.assertIn('detail', r.data)
        self.assertTrue(Department.objects.filter(id=dept.id).exists())
        Teacher.objects.all().delete()
        self.assertEqual(self.client.delete(f'/api/departments/{dept.id}/').status_code, 204)
