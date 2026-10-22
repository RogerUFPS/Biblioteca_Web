from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        start_number = self.page.start_index()

        results = [
            {
                "item_number": number,
                **item,
            }
            for number, item in enumerate(data, start=start_number)
        ]

        return Response({
            "current_page": self.page.number,
            "total_pages": self.page.paginator.num_pages,
            "page_size": self.get_page_size(self.request),
            "total_items": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": results,
        })