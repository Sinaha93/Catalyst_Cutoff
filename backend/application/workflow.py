import re

from backend.domain.errors import WorkflowError


class Workflow:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def validate_month(month):
        if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', month):
            raise WorkflowError('INVALID_MONTH', '마감월은 2000~2099년의 연월로 입력해 주세요.')

    def start(self, month):
        self.validate_month(month)
        return self.store.start(month)

    def get(self, month):
        self.validate_month(month)
        return self.store.get(month)

    def save(self, month, revision, note):
        self.validate_month(month)
        if len(note) > 10000:
            raise WorkflowError('NOTE_TOO_LONG', '작업 메모는 10,000자까지 저장할 수 있습니다.')
        return self.store.save(month, revision, note)
