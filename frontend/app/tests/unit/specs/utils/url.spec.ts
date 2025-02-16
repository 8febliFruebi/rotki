import { getDomain } from '@/utils/url';

describe('utils/url', () => {
  test('default', () => {
    expect(getDomain('https://www.google.com')).toEqual('google.com');
    expect(getDomain('http://www.google.com')).toEqual('google.com');
    expect(getDomain('www.google.com')).toEqual('google.com');
    expect(getDomain('google.com')).toEqual('google.com');
    expect(getDomain('https://www.images.google.com')).toEqual('google.com');
    expect(getDomain('https://www.images.google.co.id')).toEqual(
      'google.co.id'
    );
    expect(getDomain('https://www.images.google.ac.gov.br')).toEqual(
      'google.ac.gov.br'
    );
    expect(getDomain('not_an_url')).toEqual('not_an_url');
    expect(getDomain('.co.id')).toEqual('.co.id');
  });
});
