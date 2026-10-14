"""Operational lists must expose later records without losing active filters."""

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from apps.common.pagination import paginate


class ListPaginationTests(SimpleTestCase):
    def test_independent_pages_and_query_preservation(self):
        request = RequestFactory().get("/lists/?q=张&backup_page=2&job_page=3")
        backup_page, backup_query = paginate(request, list(range(45)), parameter="backup_page")
        job_page, job_query = paginate(request, list(range(61)), parameter="job_page")
        self.assertEqual(list(backup_page), list(range(20, 40)))
        self.assertEqual(list(job_page), list(range(40, 60)))
        self.assertIn("job_page=3", backup_query)
        self.assertNotIn("backup_page=", backup_query)
        self.assertIn("backup_page=2", job_query)
        self.assertNotIn("job_page=", job_query)

    def test_out_of_range_page_resolves_to_last_page(self):
        request = RequestFactory().get("/lists/?page=999")
        page, _query = paginate(request, list(range(21)))
        self.assertEqual(list(page), [20])

    def test_pager_has_page_jump_first_last_and_keeps_filters(self):
        request = RequestFactory().get("/lists/?q=客户&page=2")
        page, query = paginate(request, list(range(61)))
        html = render_to_string(
            "includes/list_pagination.html",
            {"page": page, "query": query, "label": "客户列表", "request": request},
        )
        self.assertIn("首页", html)
        self.assertIn("尾页", html)
        self.assertIn('data-max-page="4"', html)
        self.assertIn('name="q"', html)
        self.assertIn('value="客户"', html)
        self.assertIn('inputmode="numeric"', html)
