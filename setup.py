from setuptools import setup, find_packages

setup(
    name = "wagtail-blog",
    version = "1.6.7",
    author = "David Burke",
    author_email = "david@thelabnyc.com",
    description = ("A wordpress like blog app implemented in wagtail"),
    license = "Apache License",
    keywords = "django wagtail blog",
    url = "https://github.com/thelabnyc/wagtail_blog",
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        'Environment :: Web Environment',
        'Framework :: Django',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        'Intended Audience :: Developers',
        "License :: OSI Approved :: Apache Software License",
    ],
    install_requires=[
        'wagtail>=1.0.0',
        'Django==1.8.13',
        'wagtail==1.5.2',
        'django-hashers-passlib==0.1',
        'django-storages==1.4.1',
        'boto3',
        'django-contrib-comments==1.6.1',
        'django-comments-xtd==1.5.3',
        'django-longerusernameandemail',
        'requests',
        'lxml'
    ]
)
