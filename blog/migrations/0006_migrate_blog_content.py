# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from base64 import b64encode
from datetime import datetime
try:
    import html
except ImportError:  # 2.x
    import HTMLParser
    html = HTMLParser.HTMLParser()
import json
import os
import urllib.request
import re

import tempfile
import logging

from django.core.management.base import BaseCommand, CommandError
from django.core.files import File
from django.contrib.auth import get_user_model
User = get_user_model()
from django.contrib.auth.models import User
from django.contrib.auth.models import Group
from django_comments_xtd.models import XtdComment
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django_comments_xtd.models import MaxThreadLevelExceededException


from bs4 import BeautifulSoup
import requests

from blog.models import (BlogPage, BlogTag, BlogPageTag, BlogIndexPage,
                         BlogCategory, BlogCategoryBlogPage)
from wagtail.wagtailimages.models import Image

from xml.sax.saxutils import unescape


def migrate_blog_content(apps, schema_editor):
    blogMigrator = BlogMigrator()
    blogMigrator.start_import('https://twilioincricky.wpengine.com')

class BlogMigrator():
    def start_import(self, url):
      self.xml_path = None
      self.url = url
      self.username = None
      self.password = None
      self.should_import_comments = False

      try:
          self.blog_index = BlogIndexPage.objects.get(
              title__icontains="blog")
      except BlogIndexPage.DoesNotExist:
          raise CommandError("Have you created an index yet?")
     
      self.import_wp_data()
    
    def import_wp_data(self):
        """gets data from WordPress site"""
        page = 1
        posts = self.get_posts_data(self.url, page)
        while posts:
          self.create_blog_pages(posts, self.blog_index)
          page = page + 1
          posts = self.get_posts_data(self.url, page)

    def prepare_url(self, url):
        if url.startswith('//'):
            url = 'http:{}'.format(url)
        if url.startswith('/'):
            prefix_url = self.url
            if prefix_url.endswith('/'):
                prefix_url = prefix_url[:-1]
            url = '{}{}'.format(prefix_url, url)
        return url

    def convert_html_entities(self, text, *args, **options):
        """converts html symbols so they show up correctly in wagtail"""
        return html.unescape(text)

    def clean_data(self, data):
        # I have no idea what this junk is
        garbage = data.split("[")[0]
        data = data.strip(garbage)
        for bad_data in ['8db4ac', '\r\n', '\r\n0']:
            data = data.strip(bad_data)
        return data


    def get_posts_data(
        self, blog, page, id=None, get_comments=False, *args, **options
    ):
        if self.url == "just_testing":
            with open('test-data-comments.json') as test_json:
                return json.load(test_json)

        self.url = blog
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.153 Safari/537.36 SE 2.X MetaSr 1.0"
        }
        if self.username and self.password:
            auth = b64encode(
                str.encode('{}:{}'.format(self.username, self.password)))
            headers['Authorization'] = 'Basic {}'.format(auth)
        if self.url.startswith('https://'):
            base_url = self.url
        else:
            base_url = ''.join(('http://', self.url))
        posts_url = ''.join((base_url, '/wp-json/posts'))
        comments_url = ''.join((posts_url, '/%s/comments')) % id
        if get_comments is True:
            comments_url = ''.join((posts_url, '/%s/comments')) % id
            fetched_comments = requests.get(comments_url)
            comments_data = fetched_comments.text
            comments_data = self.clean_data(comments_data)
            return json.loads(comments_data)
        else:
            posts_url = ''.join((base_url, '/wp-json/posts'))
            fetched_posts = requests.get(posts_url +
                                           '?filter[posts_per_page]=20&page='+ str(page),
                                           headers=headers)
            print(posts_url + '?filter[posts_per_page]=20&page='+ str(page))
            data = fetched_posts.text
            data = self.clean_data(data)
            lJson = json.loads(data)
            if len(lJson) > 0 and page < 4:
              return lJson
            else:
              return False

    def format_code_in_content(self, body):
        """convert WP crayon elements into markdown for code snippets """
        soup = BeautifulSoup(body, "html5lib")
        for block in soup.findAll("div", { "class" : "crayon-syntax" }):
          # Figure out what lines of code are highlighted
          lines = block.findAll('div', {'class' : 'crayon-line'})
          i = 1
          marked_lines = []
          for line in lines:
            if "crayon-marked-line" in line['class']:
              marked_lines.append(i) 
            i = i + 1
          new_tag = soup.new_tag("div")
          language = block.find({ "class" : "crayon-language" })
          if language is None:
            language = "python"
          if marked_lines:
            language = language + ' hl_lines="' + str(marked_lines).strip('[]').replace(',', ' ') + '"'
          else:
            language = language
          new_tag.string = '```' + language + '\n' + block.find("textarea").contents[0] + '\n```'
          block.replaceWith(new_tag)
        return str(soup)

    def replace_twilioinc_urls(self, body):
      return body.replace("twilioincricky.wpengine.com","www.twilio.com/blog")

    def body_to_stream_field(self, body):
      split_body = re.split('(\```)', body)
      json_object = []
      markdown = False
      elm_string = ''
      for elm in split_body:
          if markdown:
              if elm == '```':
                  markdown = False
                  json_object.append({'type': 'markdown', 'value': elm_string + elm})
                  elm_string = ''
              else:
                  elm_string = elm_string + unescape(elm)
          else:
              if elm == '```':
                  markdown = True
                  elm_string = elm
              else:
                json_object.append({'type': 'rich_text', 'value': elm})

      return json.dumps(json_object)

    def create_images_from_urls_in_content(self, body):
        """create Image objects and transfer image files to media root"""
        soup = BeautifulSoup(body, "html5lib")
        for img in soup.findAll('img'):
            if 'width' in img:
                width = img['width']
            if 'height' in img:
                height = img['height']
            else:
                width = 100
                height = 100
            try:
                path, file_ = os.path.split(img['src'])
                if not img['src']:
                    continue  # Blank image
                if img['src'].startswith('data:'):
                    continue # Embedded image

                old_url = img['src']
                headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.153 Safari/537.36 SE 2.X MetaSr 1.0"
                }
                req = requests.get(self.prepare_url(img['src']), headers=headers, timeout=10)
                if req.status_code == 200:
                    remote_image = tempfile.NamedTemporaryFile()
                    remote_image.write(req.content)
                else:
                    remote_image = None
            except (urllib.error.HTTPError,
                    urllib.error.URLError,
                    UnicodeEncodeError,
                    requests.exceptions.SSLError, 
                    KeyError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.MissingSchema,
                    requests.exceptions.InvalidSchema,
                    requests.exceptions.InvalidURL):
                logging.warning("Unable to import image: " + img['src'])
                continue
            if len(file_) > 255:
              file_ = file_[:255]
            image = Image(title=file_, width=width, height=height)
            try:
                if remote_image and os.path.getsize(remote_image.name) > 0:
                  #TODO: Log error of files that don't import for manual fix
                  imageFile = File(open(remote_image.name, 'rb'))
                  image.file.save(file_, imageFile)
                  image.save()
                  remote_image.close()
                  new_url = image.file.url
                  body = body.replace(old_url, new_url)
                body = self.convert_html_entities(body)
            except TypeError:
                logging.warning("Unable to import image: " + img['src'])
                #print("Unable to import image {}".format(remote_image[0]))
                pass
        return body

    def create_user(self, author):
        #TODO: Set proper group permissions
        username = author['username'] + '@twilio.com'
        first_name = author['first_name']
        last_name = author['last_name']
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = User.objects.create_user(
                username=username, first_name=first_name, last_name=last_name, email=username)
        group, exists = self.create_blog_author_group()
        user.groups.add(group)
        user.save()
        return user

    def create_comment(
        self, blog_post_type, blog_post_id, comment_text, date
    ):
        new_comment = XtdComment.objects.get_or_create(
            site_id=self.site_id,
            content_type=blog_post_type,
            object_pk=blog_post_id,
            comment=comment_text,
            submit_date=date,
        )[0]
        return new_comment

    def lookup_comment_by_wordpress_id(self, comment_id, comments):
        """ Returns Django comment object with this wordpress id """
        for comment in comments:
            if comment.wordpress_id == comment_id:
                return comment

    def import_comments(self, post_id, slug, *args, **options):
        try:
            mysite = Site.objects.get_current()
            self.site_id = mysite.id
        except Site.DoesNotExist:
            print('site does not exist')
            return
        comments = self.get_posts_data(
            self.url, post_id, get_comments=True)
        imported_comments = []
        for comment in comments:
            try:
                blog_post = BlogPage.objects.get(slug=slug)
                blog_post_type = ContentType.objects.get_for_model(blog_post)
            except BlogPage.DoesNotExist:
                print('cannot find this blog post')
                continue
            comment_text = self.convert_html_entities(comment.get('content'))
            date = datetime.strptime(comment.get('date'), '%Y-%m-%dT%H:%M:%S')
            status = comment.get('status')
            if status != 'approved':
                continue
            comment_author = comment.get('author')
            new_comment = self.create_comment(
                blog_post_type, blog_post.pk, comment_text, date)
            new_comment.wordpress_id = comment.get('ID')
            new_comment.parent_wordpress_id = comment.get('parent')
            if type(comment_author) is int:
                pass
            else:
                if 'username' in comment_author:
                    user_name = comment['author']['username']
                    user_url = comment['author']['URL']
                    try:
                        current_user = User.objects.get(username=user_name)
                        new_comment.user = current_user
                    except User.DoesNotExist:
                        pass

                    new_comment.user_name = user_name
                    new_comment.user_url = user_url

            new_comment.save()
            imported_comments.append(new_comment)
        # Now assign parent comments
        for comment in imported_comments:
            if comment.parent_wordpress_id != "0":
                for sub_comment in imported_comments:
                    if sub_comment.wordpress_id == comment.parent_wordpress_id:
                        comment.parent_id = sub_comment.id
                        try:
                            comment._calculate_thread_data()
                            comment.save()
                        except MaxThreadLevelExceededException:
                            print("Warning, max thread level exceeded on {}"
                                  .format(comment.id))
                        break

    def create_categories_and_tags(self, page, categories):
        tags_for_blog_entry = []
        categories_for_blog_entry = []
        for records in categories.values():
            if records[0]['taxonomy'] == 'post_tag':
                for record in records:
                    tag_name = record['name'].lower()
                    new_tag = BlogTag.objects.get_or_create(name=tag_name)[0]
                    tags_for_blog_entry.append(new_tag)

            if records[0]['taxonomy'] == 'category':
                for record in records:
                    category_name = record['name']
                    new_category = BlogCategory.objects.get_or_create(name=category_name)[0]
                    if record.get('parent') is not None:
                        parent_category = BlogCategory.objects.get_or_create(
                            name=record['parent']['name'])[0]
                        parent_category.slug = record['parent']['slug']
                        parent_category.save()
                        parent = parent_category
                        new_category.parent = parent
                    else:
                        parent = None
                    categories_for_blog_entry.append(new_category)
                    new_category.save()

        # loop through list of BlogCategory and BlogTag objects and create
        # BlogCategoryBlogPages(bcbp) for each category and BlogPageTag objects
        # for each tag for this blog page
        for category in categories_for_blog_entry:
            BlogCategoryBlogPage.objects.get_or_create(
                category=category, page=page)[0]
        for tag in tags_for_blog_entry:
            BlogPageTag.objects.get_or_create(
                tag=tag, content_object=page)[0]

    def create_blog_pages(self, posts, blog_index, *args, **options):
        """create Blog post entries from wordpress data"""
        for post in posts:
            title = post.get('title')
            print(title)
            if title:
                new_title = self.convert_html_entities(title)
                title = new_title
            # TODO: Fix hardcoded replacement
            slug = post.get('slug') + "-html"

            description = post.get('description')
            if description:
                description = self.convert_html_entities(description)
            body = post.get('content')
            # get image info from content and create image objects
            body = self.create_images_from_urls_in_content(body)
            body = self.format_code_in_content(body)
            body = self.replace_twilioinc_urls(body)
            # author/user data
            author = post.get('author')
            user = self.create_user(author)
            categories = post.get('terms')
            # format the date
            date = post.get('date')[:10]
            body = self.body_to_stream_field(body)
            try:
                new_entry = BlogPage.objects.get(slug=slug)
                new_entry.title = title
                new_entry.body = body
                new_entry.owner = user
                new_entry.author = user
                new_entry.save()
            except BlogPage.DoesNotExist:
                new_entry = blog_index.add_child(instance=BlogPage(
                    title=title, slug=slug, search_description="description",
                    date=date, body=body, owner=user, author=user))
                print("Owner:")
                print(new_entry.owner)
            featured_image = post.get('featured_image')
            header_image = None
            if featured_image is not None and "source" in post['featured_image']:
                if 'title' in post['featured_image']:
                  title = post['featured_image']['title']
                else:
                  title = "Featured Image"
                source = post['featured_image']['source']
                path, file_ = os.path.split(source)
                source = source.replace('stage.swoon', 'swoon')
                try:
                    headers = {
                          'Content-Type': 'application/json',
                          'Accept': 'application/json',
                          'User-Agent': "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.153 Safari/537.36 SE 2.X MetaSr 1.0"
                    }
                    req = requests.get(self.prepare_url(source), headers=headers, timeout=10)
                    remote_image = tempfile.NamedTemporaryFile()
                    remote_image.write(req.content)
                    #remote_image = urllib.request.urlretrieve(
                    #    self.prepare_url(source))
                    width = 640
                    height = 290
                    if os.path.getsize(remote_image.name):
                      #TODO: Capture error for manual download
                      header_image = Image(title=title, width=width, height=height)
                      header_image.file.save(
                          file_, File(open(remote_image.name, 'rb')))
                      header_image.save()
                except UnicodeEncodeError:
                    header_image = None
                    print('unable to set header image {}'.format(source))
            else:
                header_image = None
            new_entry.header_image = header_image
            new_entry.save()
            if categories:
                self.create_categories_and_tags(new_entry, categories)
            if self.should_import_comments:
                self.import_comments(post_id, slug)

    def create_blog_author_group(self):
        return Group.objects.get_or_create(name='Blog Author')
        
       

class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0005_auto_20151019_1121'),
    ]

    operations = [
        migrations.RunPython(migrate_blog_content)
    ]
