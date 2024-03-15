import logging
import os
import re

import requests
import requests_cache
from ricecooker.chefs import SushiChef
from ricecooker.classes.nodes import TopicNode
from ricecooker.classes.nodes import DocumentNode
from ricecooker.classes.files import DocumentFile
from le_utils.constants.labels import resource_type
from le_utils.constants import roles


logger = logging.getLogger("illustratemath_chef")

# Your API and channel details
API_URL = "https://content.illustratemath.org/api/v1/"
API_KEY = os.environ["ILLUSTRATIVE_API_KEY"]


GOOGLE_SHEETS_PDF_EXPORT_URL = "https://docs.google.com/presentation/d/{PRESENTATION_ID}/export/pdf"
GOOGLE_SHEETS_ID_REGEX = re.compile("/presentation/d/([a-zA-Z0-9_-]+)/")

LICENSE = "CC BY"
DEFAULT_COPYRIGHT_HOLDER = "Illustrative Mathematics"


api_session = requests_cache.CachedSession('illustratemath_cache', expire_after=60 * 60 * 24 * 7)  # 1 week


# Chef class definition
class IllustrateMathChef(SushiChef):
    channel_info = {
        'CHANNEL_SOURCE_DOMAIN': API_URL,
        'CHANNEL_SOURCE_ID': 'illustrativemathematics',
        'CHANNEL_TITLE': 'US Common Core PBL Mathematics',
        'CHANNEL_LANGUAGE': 'en',
        'CHANNEL_DESCRIPTION': 'Project Based Learning for Mathematics, aligned to the US Common Core curriculum standards.',
        'CHANNEL_TAGLINE': 'Learn Mathematics through engaging hands on activities facilitated by a teacher.',
    }

    def fetch_data(self, endpoint):
        logger.debug("Fetching data from %s", endpoint)
        response = api_session.get(f"{API_URL}{endpoint}", headers={"api-key": API_KEY})
        response.raise_for_status()
        return response.json()["data"]

    def process_grade_bands(self, url, parent_node):
        grade_bands = self.fetch_data(url)
        for gb in grade_bands:
            gb_detail = self.fetch_data(f"{url}/{gb['id']}")
            gb_node = TopicNode(source_id=str(gb_detail['slug']), title=gb_detail['title'], description=gb_detail['description'])
            parent_node.add_child(gb_node)
            # Fetch each curriculum for the grade band
            self.process_curriculums(f"{url}/{gb_detail['id']}/curriculums", gb_node)

    def process_curriculums(self, url, parent_node):
        curriculums = self.fetch_data(url)
        for curriculum in curriculums:
            if curriculum["locale"] != "en":
                continue
            # Fetch detailed curriculum info
            curriculum_detail = self.fetch_data(f"{url}/{curriculum['id']}")
            self.copyright_holder = curriculum_detail["cc_attribution_name"]
            curriculum_node = TopicNode(source_id=str(curriculum['slug']), title=curriculum_detail['title'])
            parent_node.add_child(curriculum_node)

            # Process courses
            self.process_courses(f"{url}/{curriculum['id']}/courses", curriculum_node)

    def process_courses(self, url, parent_node):
        courses = self.fetch_data(url)
        for course in courses:
            course_detail = self.fetch_data(f"{url}/{course['id']}")
            course_node = TopicNode(source_id=str(course['slug']), title=course_detail['title'])
            parent_node.add_child(course_node)
            # Process units, assessments, etc., for the course
            self.process_units(f"{url}/{course['id']}/units", course_node)

    def process_units(self, url, parent_node):
        units = self.fetch_data(url)
        for unit in units:
            unit_detail = self.fetch_data(f"{url}/{unit['id']}")
            unit_node = TopicNode(source_id=str(unit['slug']), title=unit_detail['title'])
            parent_node.add_child(unit_node)
            # Process assessments for the unit
            # self.process_assessments(f"{url}/units/{unit['id']}/assessments", unit_node, grade_band_id, curriculum_id, course_id, unit['id'])
            # Process sections for the unit
            self.process_sections(f"{url}/{unit['id']}/sections", unit_node)

    def process_assessments(self, url, parent_node):
        assessments = self.fetch_data(url)
        for assessment in assessments:
            assessment_detail = self.fetch_data(f"{url}/{assessment['id']}")
            # TODO: Once we have QTI assessment support with free response, we should be able to support these assessments

    def process_sections(self, url, parent_node):
        sections = self.fetch_data(url)
        for section in sections:
            section_detail = self.fetch_data(f"{url}/{section['id']}")
            section_node = TopicNode(source_id=str(section_detail['slug']), title=section_detail['title'])
            parent_node.add_child(section_node)
            # Process lessons for the section
            self.process_lessons(f"{url}/{section['id']}/lessons", section_node)
            # TODO: If K5, process practice problems
            # if 'K5' in section_detail['title']:
            #     self.process_practice_problems(f"{url}/{section['id']}/practice_problems", section_node)

    def process_lessons(self, url, parent_node):
        lessons = self.fetch_data(url)
        for lesson in lessons:
            lesson_detail = self.fetch_data(f"{url}/{lesson['id']}")
            lesson_node = TopicNode(source_id=str(lesson_detail['slug']), title=lesson_detail['title'])
            parent_node.add_child(lesson_node)
            lesson_resources = self.fetch_data(f"{url}/{lesson['id']}/resources")
            for resource in lesson_resources["single_files"]:
                if resource["title"] not in {"Student Workbook", "Teacher Guide", "Curated Practice Problem Set"}:
                    continue
                for format in resource["formats"]:
                    if "pdf" in format:
                        resource_types = []
                        
                        file_data = format["pdf"]

                        if "guide" in file_data["description"].lower():
                            resource_types = [resource_type.GUIDE, resource_type.LESSON_PLAN]
                        elif "problem" in file_data["description"].lower():
                            resource_types.append(resource_type.EXERCISE)
                        elif "workbook" in file_data["description"].lower():
                            resource_types.append(resource_type.ACTIVITY)
                        document = DocumentNode(
                            source_id=str(file_data['filename']),
                            title=lesson_detail['title'] + " " + resource['title'],
                            files=[DocumentFile(path=file_data['file_url'], language='en')],
                            resource_types=resource_types,
                            license=LICENSE,
                            copyright_holder=self.copyright_holder or DEFAULT_COPYRIGHT_HOLDER,
                            role=roles.COACH,
                        )
                        lesson_node.add_child(document)
            for resource in lesson_resources["collections"]:
                if resource["title"] != "ExternalUrl":
                    continue
                for format in resource["formats"]:
                    if "urls" in format:
                        for file_data in format["urls"]:
                            if file_data["category"] == "google_slides":
                                google_slides_id = GOOGLE_SHEETS_ID_REGEX.search(file_data["href"]).group(1)
                                document = DocumentNode(
                                    source_id=google_slides_id,
                                    title=lesson_detail['title'] + " Lesson Presentation",
                                    files=[DocumentFile(path=GOOGLE_SHEETS_PDF_EXPORT_URL.format(PRESENTATION_ID=google_slides_id), language='en')],
                                    resource_types=[resource_type.LESSON],
                                    license=LICENSE,
                                    copyright_holder=self.copyright_holder or DEFAULT_COPYRIGHT_HOLDER,
                                    role=roles.COACH,
                                )
                                lesson_node.add_child(document)
                            else:
                                logger.error(file_data["category"], file_data["href"])

    def process_practice_problems(self, url, parent_node):
        practice_problems = self.fetch_data(url)
        for problem in practice_problems:
            # Assuming practice problems are documents. Adjust as necessary.
            problem_node = DocumentNode(
                source_id=str(problem['slug']),
                title=problem['title'],
                files=[DocumentFile(path=problem['file_url'], language='en')]
            )
            parent_node.add_child(problem_node)

    def construct_channel(self, *args, **kwargs):
        channel = self.get_channel(*args, **kwargs)
        self.process_grade_bands("/grade_bands", channel)
        return channel

# Main execution
if __name__ == '__main__':
    chef = IllustrateMathChef()
    chef.main()
