
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from blogs.models import Author, Blog


class Command(BaseCommand):
    help = "Seed the database with 5 authors and 25 blog posts."

    @transaction.atomic
    def handle(self, *args, **options):
        authors_data = [
            {
                "first_name": "Alice",
                "last_name": "Kim",
                "email": "alice.kim@example.com",
            },
            {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com",
            },
            {
                "first_name": "Mary",
                "last_name": "Wanjiku",
                "email": "mary.wanjiku@example.com",
            },
            {
                "first_name": "David",
                "last_name": "Mwangi",
                "email": "david.mwangi@example.com",
            },
            {
                "first_name": "Grace",
                "last_name": "Achieng",
                "email": "grace.achieng@example.com",
            },
        ]

        blogs_data = {
            "alice.kim@example.com": [
                {
                    "title": "Getting Started with Django",
                    "text": "Django is a Python web framework that simplifies web development with its ORM, URL routing, authentication, and templating system.",
                    "published_date": date(2026, 1, 10),
                },
                {
                    "title": "Understanding Django Models",
                    "text": "Django models define the structure of database tables using Python classes. They support relationships, validation, and database queries.",
                    "published_date": date(2026, 1, 15),
                },
                {
                    "title": "Working with Django Templates",
                    "text": "Django templates separate presentation from business logic and support template inheritance, filters, tags, and dynamic content.",
                    "published_date": date(2026, 2, 1),
                },
                {
                    "title": "Building Forms in Django",
                    "text": "Django forms simplify data collection and validation. ModelForm can generate forms directly from model definitions.",
                    "published_date": date(2026, 2, 12),
                },
                {
                    "title": "Django Authentication Explained",
                    "text": "Django provides user authentication, password hashing, permissions, groups, and session management for secure applications.",
                    "published_date": date(2026, 2, 20),
                },
            ],
            "john.doe@example.com": [
                {
                    "title": "Introduction to REST APIs",
                    "text": "REST APIs expose resources over HTTP and commonly use GET, POST, PUT, PATCH, and DELETE to interact with application data.",
                    "published_date": date(2026, 1, 11),
                },
                {
                    "title": "Serializers in Django REST Framework",
                    "text": "Serializers convert complex Django model instances into JSON-compatible data and validate incoming API requests.",
                    "published_date": date(2026, 1, 20),
                },
                {
                    "title": "Understanding ModelViewSet",
                    "text": "ModelViewSet provides standard CRUD actions, reducing repetitive code when building Django REST Framework APIs.",
                    "published_date": date(2026, 2, 5),
                },
                {
                    "title": "Using Routers in DRF",
                    "text": "DRF routers automatically generate URL patterns for viewsets, making API routing consistent and easier to maintain.",
                    "published_date": date(2026, 2, 16),
                },
                {
                    "title": "API Authentication and Permissions",
                    "text": "Authentication identifies a client, while permissions determine which resources and actions that client can access.",
                    "published_date": date(2026, 3, 1),
                },
            ],
            "mary.wanjiku@example.com": [
                {
                    "title": "Python Programming Best Practices",
                    "text": "Readable Python code uses descriptive names, small functions, consistent formatting, and clear separation of responsibilities.",
                    "published_date": date(2026, 1, 12),
                },
                {
                    "title": "Working with Python Lists",
                    "text": "Lists store ordered collections of items and support indexing, slicing, iteration, and common operations such as append and remove.",
                    "published_date": date(2026, 1, 25),
                },
                {
                    "title": "Python Functions and Modules",
                    "text": "Functions encapsulate reusable logic, while modules organize related functions, classes, and variables into maintainable units.",
                    "published_date": date(2026, 2, 8),
                },
                {
                    "title": "Exception Handling in Python",
                    "text": "Try and except blocks allow applications to handle expected errors gracefully and prevent failures from becoming confusing user experiences.",
                    "published_date": date(2026, 2, 19),
                },
                {
                    "title": "Introduction to Automated Testing",
                    "text": "Automated tests verify that application behavior matches expectations and help developers identify regressions during future changes.",
                    "published_date": date(2026, 3, 5),
                },
            ],
            "david.mwangi@example.com": [
                {
                    "title": "Introduction to PostgreSQL",
                    "text": "PostgreSQL is a relational database system that supports SQL, transactions, constraints, indexing, and complex queries.",
                    "published_date": date(2026, 1, 14),
                },
                {
                    "title": "Understanding SQL Joins",
                    "text": "SQL joins combine related records from multiple tables using matching columns and include INNER, LEFT, RIGHT, and CROSS JOIN.",
                    "published_date": date(2026, 1, 28),
                },
                {
                    "title": "Database Relationships Explained",
                    "text": "One-to-one, one-to-many, and many-to-many relationships help developers model connections between entities accurately.",
                    "published_date": date(2026, 2, 10),
                },
                {
                    "title": "Database Indexing Fundamentals",
                    "text": "Indexes can speed up database lookups but introduce storage overhead and may increase the cost of writes.",
                    "published_date": date(2026, 2, 22),
                },
                {
                    "title": "Database Transactions and Integrity",
                    "text": "Transactions group database operations into reliable units and help maintain consistency when errors occur.",
                    "published_date": date(2026, 3, 8),
                },
            ],
            "grace.achieng@example.com": [
                {
                    "title": "Building Modern Web Applications",
                    "text": "Modern web applications often combine a frontend framework, a backend API, and a database to deliver maintainable software.",
                    "published_date": date(2026, 1, 16),
                },
                {
                    "title": "Introduction to Git and GitHub",
                    "text": "Git tracks source code changes, while GitHub supports collaboration through repositories, pull requests, and issue tracking.",
                    "published_date": date(2026, 1, 30),
                },
                {
                    "title": "Deploying Applications to the Cloud",
                    "text": "Cloud deployment requires environment configuration, secure secrets, database connectivity, logging, and production-ready settings.",
                    "published_date": date(2026, 2, 14),
                },
                {
                    "title": "Understanding Docker Containers",
                    "text": "Docker packages applications and their dependencies into portable containers, helping teams maintain consistent development and deployment environments.",
                    "published_date": date(2026, 2, 25),
                },
                {
                    "title": "Introduction to CI/CD Pipelines",
                    "text": "Continuous integration and continuous delivery automate testing, building, and deployment to improve software delivery reliability.",
                    "published_date": date(2026, 3, 12),
                },
            ],
        }

        authors = {}

        # Create the five authors.
        for author_data in authors_data:
            author, created = Author.objects.get_or_create(
                email=author_data["email"],
                defaults=author_data,
            )

            authors[author.email] = author

            message = "Created" if created else "Already exists"
            self.stdout.write(f"{message} author: {author}")

        created_count = 0
        existing_count = 0

        # Create five blogs for each author.
        for email, posts in blogs_data.items():
            author = authors[email]

            for post_data in posts:
                blog, created = Blog.objects.get_or_create(
                    title=post_data["title"],
                    author=author,
                    defaults={
                        "text": post_data["text"],
                        "published_date": post_data["published_date"],
                    },
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Created blog: {blog.title} by {author}"
                        )
                    )
                else:
                    existing_count += 1
                    self.stdout.write(
                        f"Already exists: {blog.title}"
                    )

        self.stdout.write(
            self.style.SUCCESS(
                "\nSeeding completed successfully!\n"
                f"Authors in database: {Author.objects.count()}\n"
                f"Blogs in database: {Blog.objects.count()}\n"
                f"New blogs created: {created_count}\n"
                f"Existing blogs skipped: {existing_count}"
            )
        )
