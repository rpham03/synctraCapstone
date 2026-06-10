import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:synctra/data/services/course_import_service.dart';

void main() {
  test('course import connection errors identify the backend URL', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/course-import/'),
      type: DioExceptionType.connectionError,
      message: 'The XMLHttpRequest onError callback was called.',
    );

    final message = CourseImportService.friendlyError(error);

    expect(message, contains('Cannot reach the Synctra backend at'));
    expect(message, contains('API_BASE_URL'));
    expect(message, isNot(contains('XMLHttpRequest')));
  });

  test('course import backend detail is shown to the user', () {
    final request = RequestOptions(path: '/course-import/');
    final error = DioException(
      requestOptions: request,
      response: Response<dynamic>(
        requestOptions: request,
        statusCode: 503,
        data: {'detail': 'Colab course import agent is not configured.'},
      ),
      type: DioExceptionType.badResponse,
    );

    expect(
      CourseImportService.friendlyError(error),
      'Colab course import agent is not configured.',
    );
  });
}
