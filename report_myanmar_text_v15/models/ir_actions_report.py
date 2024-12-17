from urllib.parse import urlparse
from odoo import api, fields, models, tools, SUPERUSER_ID, _
from odoo.exceptions import UserError, AccessError
from odoo.tools.misc import find_in_path, ustr
from odoo.http import request
import os
import tempfile
import logging
import subprocess
from contextlib import closing
_logger = logging.getLogger(__name__)

def _get_wkhtmltopdf_bin():
    return find_in_path('wkhtmltopdf')


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _run_wkhtmltopdf(
            self,
            bodies,
            header=None,
            footer=None,
            landscape=False,
            specific_paperformat_args=None,
            set_viewport_size=False):
        '''Execute wkhtmltopdf as a subprocess in order to convert html given in input into a pdf
        document.

        :param list[str] bodies: The html bodies of the report, one per page.
        :param str header: The html header of the report containing all headers.
        :param str footer: The html footer of the report containing all footers.
        :param landscape: Force the pdf to be rendered under a landscape format.
        :param specific_paperformat_args: dict of prioritized paperformat arguments.
        :param set_viewport_size: Enable a viewport sized '1024x1280' or '1280x1024' depending of landscape arg.
        :return: Content of the pdf as bytes
        :rtype: bytes
        '''
        paperformat_id = self.get_paperformat()

        # Build the base command args for wkhtmltopdf bin
        command_args = self._build_wkhtmltopdf_args(
            paperformat_id,
            landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size)

        files_command_args = []
        temporary_files = []

        # Passing the cookie to wkhtmltopdf in order to resolve internal links.
        session_sid = None
        try:
            if request:
                session_sid = request.session.sid
        except AttributeError:
            pass
        else:
            base_url = self.get_base_url()
            domain = urlparse(base_url).hostname
            cookie = f'session_id={session_sid}; HttpOnly; domain={domain}; path=/;'
            cookie_jar_file_fd, cookie_jar_file_path = tempfile.mkstemp(suffix='.txt', prefix='report.cookie_jar.tmp.')
            temporary_files.append(cookie_jar_file_path)
            with closing(os.fdopen(cookie_jar_file_fd, 'wb')) as cookie_jar_file:
                cookie_jar_file.write(cookie.encode())
            command_args.extend(['--cookie-jar', cookie_jar_file_path])

        if header:
            head_file_fd, head_file_path = tempfile.mkstemp(suffix='.html', prefix='report.header.tmp.')
            with closing(os.fdopen(head_file_fd, 'wb')) as head_file:
                # Reshape the Myanmar text for PDF report
                header = self._myanmar_text_reshaper(header)
                head_file.write(header.encode())
            temporary_files.append(head_file_path)
            files_command_args.extend(['--header-html', head_file_path])
        if footer:
            foot_file_fd, foot_file_path = tempfile.mkstemp(suffix='.html', prefix='report.footer.tmp.')
            with closing(os.fdopen(foot_file_fd, 'wb')) as foot_file:
                # Reshape the Myanmar text for PDF report
                footer = self._myanmar_text_reshaper(footer)
                foot_file.write(footer.encode())
            temporary_files.append(foot_file_path)
            files_command_args.extend(['--footer-html', foot_file_path])

        paths = []
        for i, body in enumerate(bodies):
            print('----------------------------',body ,'is -----------------------------------------------------------------------------------------')
            prefix = '%s%d.' % ('report.body.tmp.', i)
            # print('-----------prefix------------',prefix,'++++++++++++++++++prefix+++++++++++++++++++++')
            body_file_fd, body_file_path = tempfile.mkstemp(suffix='.html', prefix=prefix)
            with closing(os.fdopen(body_file_fd, 'wb')) as body_file:
                # Reshape the Myanmar text for PDF report
                body = self._myanmar_text_reshaper(body)
                print(body,'======================myanmar reshaped===============================')
                body_file.write(body.encode())
            paths.append(body_file_path)
            temporary_files.append(body_file_path)

        pdf_report_fd, pdf_report_path = tempfile.mkstemp(suffix='.pdf', prefix='report.tmp.')
        os.close(pdf_report_fd)
        temporary_files.append(pdf_report_path)

        try:
            wkhtmltopdf = [_get_wkhtmltopdf_bin()] + command_args + files_command_args + paths + [pdf_report_path]
            process = subprocess.Popen(wkhtmltopdf, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = process.communicate()
            err = ustr(err)

            if process.returncode not in [0, 1]:
                if process.returncode == -11:
                    message = _(
                        'Wkhtmltopdf failed (error code: %s). Memory limit too low or maximum file number of subprocess reached. Message : %s')
                else:
                    message = _('Wkhtmltopdf failed (error code: %s). Message: %s')
                    print('----------------message is -----------', message)
                print('-----------warning',message, process.returncode, err[-1000:])
                _logger.warning(message, process.returncode, err[-1000:])
                raise UserError(message % (str(process.returncode), err[-1000:]))
            else:
                if err:
                    _logger.warning('wkhtmltopdf: %s' % err)
        except:
            raise

        with open(pdf_report_path, 'rb') as pdf_document:
            pdf_content = pdf_document.read()

        # Manual cleanup of the temporary files
        for temporary_file in temporary_files:
            try:
                os.unlink(temporary_file)
            except (OSError, IOError):
                print('--------------------Error when trying to remove file----------- %s' % temporary_file)
                _logger.error('Error when trying to remove file %s' % temporary_file)

        return pdf_content

    # Reshape the Myanmar text for PDF reports
    def _myanmar_text_reshaper(self, html):
        html_list = list(html)

        # Step - 1: Reorder the characters
        ###########
        # Reorder the 'ThaWaiHtoo' character
        for i, v in enumerate(html_list):
            if v == '\u1031':
                if html_list[i - 1] in ['\u103B', '\u103C', '\u103D', '\u103E']:
                    html_list[i - 1], html_list[i] = html_list[i], html_list[i - 1]
                    if html_list[i - 2] in ['\u103B', '\u103C', '\u103D', '\u103E']:
                        html_list[i - 2], html_list[i - 1] = html_list[i - 1], html_list[i - 2]
                        if html_list[i - 3] in ['\u103B', '\u103C', '\u103D', '\u103E']:
                            html_list[i - 3], html_list[i - 2] = html_list[i - 2], html_list[i - 3]

        # Reorder the 'YaYit' character
        for i, v in enumerate(html_list):
            if v == '\u103C':
                if html_list[i - 1] == '\u1031':
                    html_list[i - 2], html_list[i - 1], html_list[i] = '\u001D\u1031', html_list[i], html_list[i - 2]
                else:
                    html_list[i - 1], html_list[i] = html_list[i], html_list[i - 1]
                # Step 2: Character sustitutions
        #########
        # 'YaYit' character substitutions
        for i, v in enumerate(html_list):
            if v == '\u103C':
                if html_list[i + 1] in ['\u1000', '\u1003', '\u100F', '\u1006', '\u1010', '\u1011',
                                        '\u1018', '\u101A', '\u101C', '\u101E', '\u101F', '\u1021']:
                    html_list[i] = '\uE1B2'
        
        # One-to-One character substitutions
        for i, v in enumerate(html_list):
            if v == '\u1014':
                if html_list[i + 1] in ['\u102F', '\u1030', '\u103D', '\u103E']:
                    html_list[i] = '\uE107'
                if html_list[i + 2] in ['\u102F', '\u1030']:
                    html_list[i] = '\uE107'
                if html_list[i + 1] == '\u1031':
                    if html_list[i + 2] in ['\u102F', '\u1030', '\u103D', '\u103E']:
                        html_list[i], html_list[i + 1], html_list[i + 2] = '\u001D\u1031', '\uE107', html_list[i + 2]
            if v == '\u101B':
                if html_list[i + 1] in ['\u102F', '\u1030']: html_list[i] = '\uE108'
                if html_list[i + 2] in ['\u102F', '\u1030']: html_list[i] = '\uE108'
                if html_list[i + 3] in ['\u102F', '\u1030']: html_list[i] = '\uE108'
            if v == '\u102F':
                if html_list[i - 1] == '\u103B' or html_list[i - 2] == '\u103B':
                    html_list[i] = '\uE2F1'
                if html_list[i - 2] in ['\u103C', '\uE1B2'] or html_list[i - 3] in ['\u103C', '\uE1B2']:
                    html_list[i] = '\uE2F1'
            if v == '\u1030':
                if html_list[i - 1] == '\u103B' or html_list[i - 2] == '\u103B':
                    html_list[i] = '\uE2F2'
                if html_list[i - 2] in ['\u103C', '\uE1B2'] or html_list[i - 3] in ['\u103C', '\uE1B2']:
                    html_list[i] = '\uE2F2'
            if v == '\u1037':
                if html_list[i - 1] in ['\u102F', '\u1030']:
                    html_list[i] = '\uE037'
                if html_list[i - 1] == '\u1014' or html_list[i - 2] == '\u1014':
                    html_list[i] = '\uE037'
                if html_list[i - 1] == '\u101B' or html_list[i - 2] == '\u101B' or html_list[i - 3] == '\u101B':
                    html_list[i] = '\uE137'
                if html_list[i - 1] in ['\uE2F1', '\uE2F2']:
                    html_list[i] = '\uE137'
                if html_list[i - 1] == '\u103D' or html_list[i - 2] == '\u103D':
                    html_list[i] = '\uE137'
                if html_list[i - 1] == '\u103B' or html_list[i - 2] == '\u103B':
                    html_list[i] = '\uE137'
            if v == '\u103E':
                if html_list[i - 2] in ['\u103C', '\uE1B2']:
                    html_list[i] = '\uE1F3'

        reshape_html = ''.join(map(str, html_list))
        return reshape_html
