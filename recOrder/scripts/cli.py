import click
import napari
v = napari.Viewer()
v.close()
import sys
import os
from recOrder.io.zarr_converter import ZarrConverter
from waveorder.io import WaveorderReader

# From https://stackoverflow.com/questions/50975203/display-help-if-incorrect-or-mission-option-in-click
class ShowUsageOnMissingError(click.Command):
    def __call__(self, *args, **kwargs):
        try:
            return super(ShowUsageOnMissingError, self).__call__(
                *args, standalone_mode=False, **kwargs
            )
        except click.MissingParameter as exc:
            exc.ctx = None
            exc.show(file=sys.stdout)
            click.echo()
            try:
                super(ShowUsageOnMissingError, self).__call__(["--help"])
            except SystemExit:
                sys.exit(exc.exit_code)

@click.group()
def cli():
    print("\033[92mrecOrder: Computational Toolkit for Label-Free Imaging\033[0m\n")

@cli.command()
@click.argument('filename')
def info(filename):
    print(f"Reading file:\t {filename}")
    reader = WaveorderReader(filename)
    print(f"Positions:\t {reader.get_num_positions()}") 
    print(f"Time points:\t {reader.shape[0]}") 
    print(f"Channels:\t {reader.shape[1]}") 
    print(f"(Z, Y, X):\t {reader.shape[2:]}") 
    print(f"Channel names:\t {reader.channel_names}") 
    print(f"Z step size:\t {reader.z_step_size}")
    print("")
    
cli.add_command(info)

@cli.command()
@click.argument('filename')
@click.option('--position','-p', default=None, multiple=True)
def view(filename, position=None):
    print(f"Reading file:\t {filename}")
    reader = WaveorderReader(filename)

    if position == ():
        position = range(reader.get_num_positions())

    v = napari.Viewer()
    for i in position:
        v.add_image(reader.get_zarr(int(i)), name=reader.stage_positions[int(i)]['Label'])
    
    napari.run()
    
cli.add_command(view)


@click.command()
@click.help_option("-h", "--help")
def help():
    """\033[92mrecOrder: Computational Toolkit for Label-Free Imaging\033[0m

    To use recOrder\'s napari plugin, use \033[96mnapari -w recOrder-napari\033[0m

    To convert MicroManager .tif files to ome-zarr data format use \033[96mrecOrder.convert\033[0m

    Thank you for using recOrder.
    """
    print(help.__doc__)


@click.command(cls=ShowUsageOnMissingError)
@click.help_option("-h", "--help")
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True),
    help="path to the raw data folder containing ome.tifs",
)
@click.option(
    "--output",
    required=True,
    type=str,
    help="full path to save the zarr store (../../Experiment.zarr)",
)
@click.option(
    "--data_type",
    required=False,
    type=str,
    help='Data type, "ometiff", "upti", "zarr"',
)
@click.option(
    "--replace_pos_name",
    required=False,
    type=bool,
    help="whether or not to append position name to data",
)
@click.option(
    "--format_hcs",
    required=False,
    type=bool,
    help='whether or not to format the data as an HCS "well-plate"',
)
def convert(input, output, data_type, replace_pos_name, format_hcs):
    converter = ZarrConverter(
        input, output, data_type, replace_pos_name, format_hcs
    )
    converter.run_conversion()
