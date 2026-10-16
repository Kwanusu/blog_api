from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from school.models import Course, Department, Enrollment, Student, Teacher

DEPARTMENTS = [
    ("Computer Science", "Programming, software engineering and data."),
    ("Mathematics", "Pure and applied mathematics."),
    ("Sciences", "Physics, chemistry and biology."),
    ("Languages", "English, Kiswahili and literature."),
]

TEACHERS = [
    ("Peter", "Otieno", "peter.otieno@school.example.com", "Computer Science"),
    ("Susan", "Njeri", "susan.njeri@school.example.com", "Computer Science"),
    ("James", "Kamau", "james.kamau@school.example.com", "Mathematics"),
    ("Faith", "Chebet", "faith.chebet@school.example.com", "Sciences"),
    ("Hassan", "Omar", "hassan.omar@school.example.com", "Languages"),
]

STUDENTS = [
    ("Amina", "Yusuf", "amina.yusuf@school.example.com", "ADM001", date(2009, 3, 14)),
    ("Brian", "Mutua", "brian.mutua@school.example.com", "ADM002", date(2008, 7, 2)),
    ("Cynthia", "Wambui", "cynthia.wambui@school.example.com", "ADM003", date(2009, 11, 21)),
    ("Daniel", "Kiprop", "daniel.kiprop@school.example.com", "ADM004", date(2008, 1, 30)),
    ("Esther", "Akinyi", "esther.akinyi@school.example.com", "ADM005", date(2009, 5, 9)),
    ("Felix", "Mwangi", "felix.mwangi@school.example.com", "ADM006", date(2008, 9, 17)),
    ("Grace", "Atieno", "grace.atieno@school.example.com", "ADM007", date(2009, 12, 3)),
    ("Hillary", "Rotich", "hillary.rotich@school.example.com", "ADM008", date(2008, 4, 25)),
    ("Irene", "Nyambura", "irene.nyambura@school.example.com", "ADM009", date(2009, 8, 12)),
    ("Joel", "Barasa", "joel.barasa@school.example.com", "ADM010", date(2008, 2, 6)),
]

# code, name, department, teacher emails
COURSES = [
    ("CS101", "Introduction to Programming", "Computer Science", ["peter.otieno@school.example.com"]),
    ("CS201", "Web Development", "Computer Science",
     ["peter.otieno@school.example.com", "susan.njeri@school.example.com"]),
    ("MTH101", "Algebra", "Mathematics", ["james.kamau@school.example.com"]),
    ("MTH201", "Calculus", "Mathematics", ["james.kamau@school.example.com"]),
    ("SCI101", "Biology Basics", "Sciences", ["faith.chebet@school.example.com"]),
    ("SCI102", "Chemistry Basics", "Sciences", ["faith.chebet@school.example.com"]),
    ("LNG101", "English Composition", "Languages", ["hassan.omar@school.example.com"]),
]

# admission number -> [(course code, grade)]
ENROLLMENTS = {
    "ADM001": [("CS101", "A"), ("MTH101", "B"), ("LNG101", "")],
    "ADM002": [("CS101", "B"), ("CS201", ""), ("SCI101", "C")],
    "ADM003": [("MTH101", "A"), ("MTH201", "A"), ("SCI102", "")],
    "ADM004": [("CS101", "C"), ("LNG101", "B")],
    "ADM005": [("CS201", "A"), ("SCI101", "B"), ("LNG101", "")],
    "ADM006": [("MTH101", "B"), ("SCI102", "C")],
    "ADM007": [("CS101", "A"), ("CS201", "B"), ("MTH201", "")],
    "ADM008": [("SCI101", "B"), ("SCI102", "A")],
    "ADM009": [("LNG101", "A"), ("MTH101", "")],
    "ADM010": [("CS101", ""), ("SCI101", "C"), ("MTH201", "B")],
}

# Demo logins (email is the login) linked to teacher/student records by email.
DEMO_TEACHER_EMAILS = [
    "peter.otieno@school.example.com",
    "james.kamau@school.example.com",
]
DEMO_STUDENT_EMAILS = [
    "amina.yusuf@school.example.com",
    "brian.mutua@school.example.com",
]
DEMO_EDITOR_EMAIL = "school_editor@school.example.com"


class Command(BaseCommand):
    help = (
        "Seed the school app with departments, teachers, students, courses and "
        "enrollments, plus demo logins linked to some teachers/students. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-users",
            action="store_true",
            help="Skip creating the demo login accounts.",
        )
        parser.add_argument(
            "--password",
            default="ChangeMe-12345",
            help="Password for newly created demo logins (default: %(default)s).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        departments = {}
        for name, description in DEPARTMENTS:
            dept, _ = Department.objects.get_or_create(
                name=name, defaults={"description": description}
            )
            departments[name] = dept

        teachers = {}
        for first, last, email, dept_name in TEACHERS:
            teacher, _ = Teacher.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "department": departments[dept_name],
                },
            )
            teachers[email] = teacher

        students = {}
        for first, last, email, adm, dob in STUDENTS:
            student, _ = Student.objects.get_or_create(
                admission_number=adm,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "date_of_birth": dob,
                },
            )
            students[adm] = student

        courses = {}
        for code, name, dept_name, teacher_emails in COURSES:
            course, _ = Course.objects.get_or_create(
                code=code,
                defaults={"name": name, "department": departments[dept_name]},
            )
            course.teachers.add(*[teachers[e] for e in teacher_emails])
            courses[code] = course

        enrollments_created = 0
        for adm, entries in ENROLLMENTS.items():
            for code, grade in entries:
                _, created = Enrollment.objects.get_or_create(
                    student=students[adm],
                    course=courses[code],
                    defaults={"grade": grade},
                )
                enrollments_created += created

        if not options["no_users"]:
            self._seed_users(options["password"], teachers, students)

        self.stdout.write(
            self.style.SUCCESS(
                "School seeding completed.\n"
                f"Departments: {Department.objects.count()}\n"
                f"Teachers: {Teacher.objects.count()}\n"
                f"Students: {Student.objects.count()}\n"
                f"Courses: {Course.objects.count()}\n"
                f"Enrollments: {Enrollment.objects.count()} "
                f"({enrollments_created} new)"
            )
        )


    def _seed_users(self, password, teachers, students):
        def make_user(email, role):
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"role": role},
            )

            # Ensure existing accounts have a usable password.
            if created or not user.has_usable_password():
                user.set_password(password)
                user.save(update_fields=["password"])

                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f"Created {role} login: {email}")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Set a password for existing account: {email}"
                        )
                    )

            return user

        # Link teacher records to their login accounts.
        for email in DEMO_TEACHER_EMAILS:
            teacher = teachers[email]
            user = make_user(email, User.Role.TEACHER)

            if teacher.user_id != user.id:
                teacher.user = user
                teacher.save(update_fields=["user"])

        # Link student records to their login accounts.
        for email in DEMO_STUDENT_EMAILS:
            student = next(
                s for s in students.values()
                if s.email == email
            )
            user = make_user(email, User.Role.STUDENT)

            if student.user_id != user.id:
                student.user = user
                student.save(update_fields=["user"])

        # Ensure the editor account also has a usable password.
        make_user(DEMO_EDITOR_EMAIL, User.Role.EDITOR)
