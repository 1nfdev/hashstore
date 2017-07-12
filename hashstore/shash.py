import logging
from hashstore.utils import print_pad


def args_parser():
    import argparse

    parser = argparse.ArgumentParser(description='shash - hashstore backup client')

    parser.add_argument('command', choices=COMMANDS)

    parser.set_defaults(secure=None, debug=False)

    parser.add_argument('--url', metavar='url', nargs='?',
                        default=None,
                        help='a url where server is running')
    parser.add_argument('--invitation', metavar='invitation', nargs='?',
                        default=None,
                        help='invitation received from server')
    parser.add_argument('--dir', metavar='dir', nargs='?',
                        default='.',
                        help='directory to be backed up')
    parser.add_argument('--dest', metavar='dest', nargs='?',
                        default=None,
                        help='destination directory where '
                             'files will be restored')
    parser.add_argument('--udk', metavar='udk', nargs='?',
                        default=None,
                        help='version of directory to be restored')
    parser.add_argument('--debug', dest="debug", action='store_true',
                        help='change loginin leve to debug. '
                             'default is INFO')
    return parser

COMMANDS = 'register backup restore scan ls'.split()


def main():
    parser = args_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level)

    cmd_picked = [args.command == n for n in COMMANDS]
    doing = dict(zip(COMMANDS, cmd_picked))

    import hashstore.dir_scan as dscan
    if doing['ls']:
        shamo = dscan.Shamo(args.dir)
        usage = shamo.directory_usage()
        print(shamo.dir_id())
        print_pad(usage, 'file_type size name'.split())
        print('total_size: %d' % sum( r['size'] for r in usage))
    elif doing['scan']:
        udk = dscan.DirScan(args.dir).udk
        print(udk)
    else:
        m = dscan.Remote(args.dir)
        if doing['register']:
            m.register(args.url,args.invitation)
        elif doing['backup']:
            print(m.backup())
        else: # doing['restore']:
            m.restore(args.udk,args.dest)

if __name__ == '__main__':
    main()