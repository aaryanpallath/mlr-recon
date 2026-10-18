-- The exceptions queue is filtered by status and category; index those.
CREATE INDEX exceptions_status_idx   ON exceptions (reporting_year, status);
CREATE INDEX exceptions_category_idx ON exceptions (reporting_year, category);
