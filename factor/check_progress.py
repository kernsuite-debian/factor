"""
Module that checks and displays the progress of a run
"""
import sys
import os
import subprocess
import shutil
import numpy as np
import pickle
import logging
import glob
import ConfigParser
import factor
import factor.directions
import factor.parset
import casacore.images as pim
import ast
from astropy.coordinates import Angle
from shapely.geometry import Polygon as SPolygon
from lofarpipe.support.data_map import DataMap
from lofarpipe.support.parset import Parset
from factor.lib.direction import Direction
try:
    from matplotlib import pyplot as plt
    from matplotlib.patches import Polygon, Circle
    from matplotlib.ticker import FuncFormatter
    from mpl_toolkits.axes_grid.anchored_artists import AnchoredText
except Exception as e:
    raise ImportError('PyPlot could not be imported. Plotting is not '
        'available: {0}'.format(e.message))
try:
    try:
        from astropy.visualization.wcsaxes import WCSAxes
        hasWCSaxes = True
    except:
        from wcsaxes import WCSAxes
        hasWCSaxes = True
except:
    hasWCSaxes = False
try:
    import aplpy
    from factor.scripts import make_selfcal_images
    hasaplpy = True
except:
    hasaplpy = False

try:
    import pyds9
    haspyds9 = True
except:
    haspyds9 = False

log = logging.getLogger('factor:progress')
logging.getLogger('astropy').setLevel(logging.CRITICAL)
logging.getLogger('factor:parset').setLevel(logging.CRITICAL)
logging.getLogger('factor:directions').setLevel(logging.CRITICAL)


def show_instructions():
    log.info('Left-click on a direction to select it and see its current state')
    log.info('Right-click on a direction to deselect it')
    log.info('(In both cases, pan/zoom mode must be off)')
    log.info('Press "c" to display calibrator selfcal images for selected direction')
    log.info('Press "i" to display facet image for selected direction')
    log.info('Press "v" to display facet verify image for selected direction')
    log.info('Press "t" to display TEC solutions for selected direction')
    log.info('Press "g" to display Gain solutions for selected direction')
    log.info('Press "u" to update display (display is updated automatically every minute)')
    log.info('Press "h" to repeat these instructions on this terminal')

def run(parset_file, trim_names=True):
    """
    Displays the current progress of a run
    """
    global all_directions
    global options

    # Read in parset and get directions
    all_directions, options = load_directions(parset_file)
    if len(all_directions) == 0:
        log.error('No directions found. Please check the parset or wait until '
            'Factor has initialized the directions')
        sys.exit(1)

    # Check for other assignments of the shortcuts we want to use and, if found,
    # remove them from rcParams
    factor_keys = ['u', 'c', 'i', 't', 'g', 'h','v']
    for k in plt.rcParams.iterkeys():
        if 'keymap' in k:
            for key in factor_keys:
                if type(plt.rcParams[k]) is list:
                    if key in plt.rcParams[k]:
                        indx = plt.rcParams[k].index(key)
                        plt.rcParams[k][indx] = ''
                elif key == plt.rcParams[k]:
                    plt.rcParams[k] = ''

    # Plot field
    log.info('Plotting directions...')
    show_instructions()
    plot_state(all_directions, trim_names=trim_names)


def load_directions(parset_file):
    """
    Return directions for a run and any checkfactor-specific options
    """
    # Read parset
    parset = factor.parset.parset_read(parset_file, use_log_file=False)
    options = parset['checkfactor']

    # Figure out whether reimaging is going to be done and if so how
    # many images are to be made.
    imaging_parset = parset['imaging_specific']
    reimages=len(imaging_parset['facet_cellsize_arcsec'])
    options['reimages']=reimages

    # Load directions. First check for user-supplied directions file then for
    # Factor-generated file from a previous run
    direction_list = []
    dir_parset = parset['direction_specific']
    if 'directions_file' in dir_parset:
        directions = factor.directions.directions_read(dir_parset['directions_file'],
            parset['dir_working'])
    elif os.path.exists(os.path.join(parset['dir_working'], 'factor_directions.txt')):
        directions = factor.directions.directions_read(os.path.join(parset['dir_working'],
            'factor_directions.txt'), parset['dir_working'])
    else:
        log.error('No directions found. Please run this tool after '
            'the directions have been defined')
        sys.exit(1)

    # Add the target to the directions list if desired
    target_ra = dir_parset['target_ra']
    target_dec = dir_parset['target_dec']
    target_radius_arcmin = dir_parset['target_radius_arcmin']
    target_has_own_facet = dir_parset['target_has_own_facet']
    if target_has_own_facet:
        if target_ra is not None and target_dec is not None and target_radius_arcmin is not None:
            # Make target object
            target = Direction('target', target_ra, target_dec,
                factor_working_dir=parset['dir_working'])

            # Add target to directions list
            directions.append(target)
        else:
            log.critical('target_has_own_facet = True, but target RA, Dec, or radius not found in parset')
            sys.exit(1)

    for direction in directions:
        has_state = direction.load_state()
        if has_state:
            direction_list.append(direction)

    return direction_list, options


def plot_state(directions_list, trim_names=True):
    """
    Plots the facets of a run
    """
    global midRA, midDec, fig, at, selected_direction, choose_from_list
    selected_direction = None
    choose_from_list = False

    # Set up coordinate system and figure
    points, midRA, midDec = factor.directions.getxy(directions_list)
    fig = plt.figure(1, figsize=(10,9))
    if hasWCSaxes:
        wcs = factor.directions.makeWCS(midRA, midDec)
        ax = WCSAxes(fig, [0.16, 0.1, 0.8, 0.8], wcs=wcs)
        fig.add_axes(ax)
    else:
        ax = plt.gca()

    field_x = min(points[0])
    field_y = max(points[1])
    adjust_xy = True
    while adjust_xy:
        adjust_xy = False
        for xy in points:
            dist = np.sqrt( (xy[0] - field_x)**2 + (xy[1] - field_y)**2 )
            if dist < 10.0:
                field_x -= 1
                field_y += 1
                adjust_xy = True
                break
    field_ra, field_dec = factor.directions.xy2radec([field_x], [field_y],
        refRA=midRA, refDec=midDec)
    field = Direction('field', field_ra[0], field_dec[0],
        factor_working_dir=directions_list[0].working_dir)
    directions_list.append(field)

    ax.set_title('Overview of Factor run in\n{}'.format(directions_list[0].working_dir))

    # Plot facets
    markers = []
    for direction in directions_list:
        if direction.name != 'field':
            vertices = read_vertices(direction.vertices_file)
            RAverts = vertices[0]
            Decverts = vertices[1]
            xverts, yverts = factor.directions.radec2xy(RAverts, Decverts,
                refRA=midRA, refDec=midDec)
            xyverts = [np.array([xp, yp]) for xp, yp in zip(xverts, yverts)]
            mpl_poly = Polygon(np.array(xyverts), edgecolor='#a9a9a9', facecolor='#F2F2F2',
                clip_box=ax.bbox, picker=3.0, linewidth=2)
        else:
            xverts = [field_x]
            yverts = [field_y]
            mpl_poly = Circle((field_x, field_y), radius=5.0, edgecolor='#a9a9a9', facecolor='#F2F2F2',
                clip_box=ax.bbox, picker=3.0, linewidth=2)
        mpl_poly.facet_name = direction.name
        mpl_poly.completed_ops = get_completed_ops(direction)
        mpl_poly.started_ops = get_started_ops(direction)
        mpl_poly.current_op = get_current_op(direction)
        set_patch_color(mpl_poly, direction)
        ax.add_patch(mpl_poly)

        # Add facet names
        if direction.name != 'field':
            poly_tuple = tuple([(xp, yp) for xp, yp in zip(xverts, yverts)])
            xmid = SPolygon(poly_tuple).centroid.x
            ymid = SPolygon(poly_tuple).centroid.y
        else:
            xmid = field_x
            ymid = field_y
        if trim_names:
            name = direction.name.split('_')[-1]
        else:
            name = direction.name
        marker = ax.text(xmid, ymid, name, color='k', clip_on=True,
            clip_box=ax.bbox, ha='center', va='bottom')
        marker.set_zorder(1001)
        markers.append(marker)

    # Add info box
    at = AnchoredText("Selected direction: None", prop=dict(size=12), frameon=True,
        loc=3)
    at.patch.set_boxstyle("round,pad=0.,rounding_size=0.2")
    at.set_zorder(1002)
    ax.add_artist(at)

    ax.relim()
    ax.autoscale()
    ax.set_aspect('equal')

    if hasWCSaxes:
        RAAxis = ax.coords['ra']
        RAAxis.set_axislabel('RA', minpad=0.75)
        RAAxis.set_major_formatter('hh:mm:ss')
        DecAxis = ax.coords['dec']
        DecAxis.set_axislabel('Dec', minpad=0.75)
        DecAxis.set_major_formatter('dd:mm:ss')
        ax.coords.grid(color='black', alpha=0.5, linestyle='solid')
    else:
        plt.xlabel("RA (arb. units)")
        plt.ylabel("Dec (arb. units)")

    # Define coodinate formater to show RA and Dec under mouse pointer
    ax.format_coord = formatCoord

    # Show legend
    not_processed_patch = plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
        facecolor='#F2F2F2', linewidth=2)
    processing_patch = plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
        facecolor='#F2F5A9', linewidth=2)
    selfcal_ok_patch = plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
        facecolor='#A9F5A9', linewidth=2)
    selfcal_not_ok_patch = plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
        facecolor='#A4A4A4', linewidth=2)
    processing_error = plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
        facecolor='#F5A9A9', linewidth=2)
    patch_list=[not_processed_patch, processing_patch, processing_error, selfcal_not_ok_patch, selfcal_ok_patch]
    label_list=['Unprocessed', 'Processing', 'Pipeline Error', 'Selfcal Failed', 'Selfcal OK']
    for i in range(options['reimages']):
        label_list.append('Image '+str(i+1))
        color=(0.66/(i+2)**0.5, 0.96/(i+2)**0.5, 0.66/(i+2)**0.5, 1.0)
        reimage_patch=plt.Rectangle((0, 0), 1, 1, edgecolor='#a9a9a9',
            facecolor=color, linewidth=2)
        patch_list.append(reimage_patch)
    l = ax.legend(patch_list, label_list, loc="upper right")
    l.set_zorder(1002)

    # Add check for mouse clicks and key presses
    fig.canvas.mpl_connect('pick_event', on_pick)
    fig.canvas.mpl_connect('key_press_event', on_press)

    # Add timer to update the plot every 60 seconds
    timer = fig.canvas.new_timer(interval=60000)
    timer.add_callback(update_plot)
    timer.start()

    # Show plot
    plt.show()
    plt.close(fig)

    # Clean up any temp casacore images
    if not hasaplpy:
        if os.path.exists('/tmp/tempimage'):
            try:
                shutil.rmtree('/tmp/tempimage')
            except OSError:
                pass


def on_pick(event):
    """
    Handle picks with the mouse
    """
    global all_directions, at, fig, selected_direction, choose_from_list

    choose_from_list = False
    facet = event.artist
    direction = None
    if hasattr(facet, 'facet_name'):
        for d in all_directions:
            if d.name == facet.facet_name:
                direction = d
                break
        if direction is None:
            selected_direction = None
            return
    else:
        selected_direction = None
        return

    if event.mouseevent.button == 1: # left click
        # Print info and set current selection to this direction
        c = at.get_child()
        c.set_text('Getting info...')
        if selected_direction is not None:
            if direction.name != selected_direction.name:
                unset_highlight()
        selected_direction = direction
        set_highlight()
        fig.canvas.draw()
        info = get_current_info(direction)

        # Update text box
        c = at.get_child()
        c.set_text(info)

        # Redraw
        fig.canvas.draw()
    elif event.mouseevent.button == 3: # right click
        # Deselect selected direction (if any)
        if selected_direction is not None:
            unset_highlight()
            selected_direction = None

            # Update text box
            c = at.get_child()
            c.set_text("Selected direction: None")

            # Redraw
            fig.canvas.draw()


def get_current_info(direction):
    """
    Returns string of current state info
    """
    info = 'Selected direction: {}\n'.format(direction.name)

    if not direction.load_state():
        info += 'State not available'
        return info

    completed_ops = get_completed_ops(direction)
    completed_ops_lines = wrap(', '.join(completed_ops))
    if len(completed_ops) == 0:
        info += 'Completed ops: None\n'
    else:
        info += 'Completed ops: {}\n'.format('\n  '.join(completed_ops_lines))

    current_op = get_current_op(direction)
    info += 'Current op: {}'.format(current_op)
    if current_op is not None:
        current_step, current_index, num_steps, start_time = get_current_step(direction)
        if current_step is not None:
            info += '\n- Started at: {}\n'.format(start_time)
            info += '- Current step: {0} (step {1} of {2})'.format(
                current_step, current_index+1, num_steps)
        else:
            info += '\n- Waiting for state update...'

    return info


def on_press(event):
    """
    Handle key presses
    """
    global fig, at, selected_direction, choose_from_list

    if event.key == 'u':
        # Update plot
        choose_from_list = False
        update_plot()
        return

    elif event.key == 'c':
        # Open selfcal images (if any)
        choose_from_list = False
        if selected_direction is None:
            return
        selfcal_images = find_selfcal_images(selected_direction)
        if len(selfcal_images) > 0:
            info = 'Opening selfcal images for {}...'.format(selected_direction.name)
            if hasaplpy:
                # Update the text box as the call below takes a few seconds
                c = at.get_child()
                c.set_text(info)
                fig.canvas.draw()
                make_selfcal_images.main(selfcal_images, interactive=True,
                    facet_name=selected_direction.name)
            else:
                if os.path.exists('/tmp/tempimage'):
                    shutil.rmtree('/tmp/tempimage')
                im = pim.image(selfcal_images)
                im.view()
        else:
            info = 'No selfcal images exist for {}'.format(selected_direction.name)

    elif event.key == 'i':
        # Open full facet images (if any)
        if selected_direction is None:
            return
        facet_images, facetimage_ops = find_facet_images(selected_direction)
        if len(facet_images) == 0:
            info = 'No image of facet exists for {}'.format(selected_direction.name)
        else:
            info = 'Load facet image from (choose one):'
            for opindx, (img, fimg_op) in enumerate(zip(facet_images, facetimage_ops)):
                info += '\n  ({0}) {1}'.format(opindx+1, fimg_op)
            choose_from_list = True


    elif event.key == 'v':
        # Open full facet images (if any)
        choose_from_list = False
        if selected_direction is None:
            return
        facet_verify_images = find_facet_verify_images(selected_direction)
        if len(facet_verify_images) == 0:
            info = 'No verify image of facet exists for {}'.format(selected_direction.name)
        else:
            info = 'Opening selfcal verification images for {}...'.format(selected_direction.name)
        display_image(facet_verify_images)

    elif event.key in [str(num+1) for num in range(9)]:
        # Open image (from list given on "i" press)
        if choose_from_list:
            facet_images, facetimage_ops = find_facet_images(selected_direction)
            if int(event.key) <= len(facet_images):
                display_image(facet_images[int(event.key)-1])
                return
        else:
            return

    elif event.key == 't':
        # Open fast TEC selfcal plots (if any)
        choose_from_list = False
        if selected_direction is None:
            return
        selfcal_plots = find_selfcal_tec_plots(selected_direction)
        if len(selfcal_plots) > 0:
            info = 'Opening selfcal TEC solution plots for {}...'.format(selected_direction.name)
            os.system(options['image_display']+' {} &'.format(' '.join(selfcal_plots)))
        else:
            info = 'Final selfcal solutions do not exist for {}'.format(selected_direction.name)

    elif event.key == 'g':
        # Open slow Gain selfcal plots (if any)
        choose_from_list = False
        if selected_direction is None:
            return
        selfcal_plots = find_selfcal_gain_plots(selected_direction)
        if len(selfcal_plots) > 0:
            info = 'Opening selfcal Gain solution plots for {}...'.format(selected_direction.name)
            os.system(options['image_display']+' {} &'.format(' '.join(selfcal_plots)))
        else:
            info = 'Final selfcal solutions do not exist for {}'.format(selected_direction.name)

    elif event.key == 'h':
        choose_from_list = False
        info='Reprinting instructions'
        show_instructions()
        return

    else:
        return

    # Update info box
    c = at.get_child()
    c.set_text(info)
    fig.canvas.draw()


def display_image(images):
    """
    Displays images in an external viewer
    """
    global fig, at, selected_direction

    if not isinstance(images, list):
        images = [images]

    if options['facet_viewer'] == 'casa':
        for image in images:
            im2 = pim.image(image)
            im2.view()
    elif options['facet_viewer'] == 'ds9':
        for i in range(len(images)):
            image = images[i]
            if os.path.isdir(image):
                # Convert casa image to fits
                if not os.path.exists('{0}.fits'.format(image)):
                    subprocess.call('image2fits in={0} out={0}.fits'.format(image),
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                images[i] = '{0}.fits'.format(image)
        if not haspyds9:
            os.system('ds9 -tile {} &'.format(' '.join(images)))
        else:
            # use pyds9 if available to re-use an existing ds9
            pyds9.ds9_xpans()
            c = at.get_child()
            info_last = c.get_text()
            info = 'Opening image in ds9...'
            c.set_text(info)
            fig.canvas.draw()
            ds9=pyds9.DS9('checkfactor', wait=120)
            c.set_text(info_last)
            fig.canvas.draw()
            for i in range(len(images)):
                if options['ds9_frames'] == 'current':
                    if len(images) > 1:
                        # For single image, no need to set frame as current one
                        # is used by default. For multiple images, use frame i
                        # for image i
                        ds9.set('frame {:d}'.format(i))
                elif options['ds9_frames'] == 'new':
                    ds9.set('frame new')
                else:
                    log.warning('ds9_frames setting "{}" not understood. Using '
                        '"new" instead'.format(options['ds9_frames']))
                    ds9.set('frame new')
                ds9.set('file '+images[i])
                if options['ds9_limits'] is not None:
                    ds9.set('scale limits '+options['ds9_limits'])
                if options['ds9_load_regions']:
                    regionfile=os.path.join(selected_direction.working_dir,'regions','facets_ds9.reg')
                    ds9.set('regions delete all')
                    ds9.set('regions load '+regionfile)
            if len(images) > 1:
                ds9.set('tile')
                ds9.set('frame match scale and limits')
                ds9.set('frame match colorbar')
                ds9.set('frame match wcs')
    else:
        info = 'Unknown facet viewer specified in config file!'
        c = at.get_child()
        c.set_text(info)
        fig.canvas.draw()


def update_plot():
    """
    Update the plot
    """
    global fig, all_directions, at, selected_direction

    ax = plt.gca()
    c = at.get_child()

    # Update colors and text box
    info_last = c.get_text()
    info = 'Updating display...'
    c.set_text(info)
    fig.canvas.draw()
    for a in ax.patches:
        if hasattr(a, 'facet_name'):
            for d in all_directions:
                if d.name == a.facet_name:
                    set_patch_color(a, d)
                    if selected_direction is not None:
                        if d.name == selected_direction.name:
                            set_highlight()
                    break

    info = info_last
    if selected_direction is not None:
        info_new = get_current_info(selected_direction)
        if 'Current op:' in info_last:
            # Replace last info with new info only if it was showing the
            # current state
            info = info_new
    c.set_text(info)
    fig.canvas.draw()


def set_patch_color(a, d):
    """
    Sets face and edge color of patch depending on its state
    """
    global selected_direction

    if not d.load_state():
        # Means that state is not available, so set to unprocessed
        a.set_edgecolor('#a9a9a9')
        a.set_facecolor('#F2F2F2')
        return

    a.completed_ops = get_completed_ops(d)
    a.started_ops = get_started_ops(d)
    a.current_op = get_current_op(d)
    if a.current_op is not None:
        a.current_step, current_index, num_steps, start_time = get_current_step(d)
        has_error = check_for_error(d, start_time)
        if has_error:
            # Pipeline failed due to error
            a.set_edgecolor('#a9a9a9')
            a.set_facecolor('#F5A9A9')
            return

    total_completed = max(0, len(a.completed_ops)-1)
    if d.name == 'field':
        # Increase by two to skip facetselfcal + facetsub for field, as they do not apply
        total_completed += 2
    nimages = 0
    for op in a.completed_ops:
        if 'facetimage' in op:
            nimages += 1
        if 'facetsubreset' in op:
            total_completed -= 1
    if nimages-1 == total_completed:
        # facetselfcal was skipped (or failed), so increment by two to compensate
        total_completed += 2

    # treat facetselfcal and facetsub as one op for consistency with old code
    if total_completed==0:
        total_completed=1
    completed_color=(0.66/total_completed**0.5,0.96/total_completed**0.5,0.66/total_completed**0.5,1.0)
    if a.current_op is not None and a.current_step is not None:
        # Means this facet is currently processing
        a.set_edgecolor('#a9a9a9')
        a.set_facecolor('#F2F5A9')
    elif 'facetselfcal' in a.completed_ops:
        if verify_subtract(d):
            a.set_edgecolor('#a9a9a9')
            a.set_facecolor(completed_color)
        else:
            # Failed selfcal
            a.set_edgecolor('#a9a9a9')
            a.set_facecolor('#A4A4A4')
    elif len(a.completed_ops) > 0:
        # normally never run since facetselfcal will be first op
        a.set_edgecolor('#a9a9a9')
        a.set_facecolor(completed_color)


def set_highlight():
    """
    Highlights selected direction border
    """
    global selected_direction

    ax = plt.gca()
    for a in ax.patches:
        if hasattr(a, 'facet_name'):
            if selected_direction.name == a.facet_name:
                a.set_zorder(1000)
                a.set_edgecolor('#FFFF00')
                a.set_linewidth(4)


def unset_highlight():
    """
    Unhighlights selected direction border
    """
    global selected_direction

    ax = plt.gca()
    for a in ax.patches:
        if hasattr(a, 'facet_name'):
            if selected_direction.name == a.facet_name:
                a.set_zorder(1)
                a.set_edgecolor('#a9a9a9')
                a.set_linewidth(2)


def get_completed_ops(direction):
    """
    Returns list of completed operations
    """
    has_state = direction.load_state()
    if has_state:
        return direction.completed_operations
    else:
        return []


def get_started_ops(direction):
    """
    Returns list of started operations
    """
    has_state = direction.load_state()
    if has_state:
        return direction.started_operations
    else:
        return []


def get_current_op(direction):
    """
    Returns name of current op (assumes there is just one)
    """
    started_ops = get_started_ops(direction)
    completed_ops = get_completed_ops(direction)
    started_but_not_completed_ops = [op for op in started_ops if not op in completed_ops]

    if len(started_but_not_completed_ops) == 0:
        return None
    else:
        return started_but_not_completed_ops[-1]


def find_selfcal_images(direction):
    """
    Returns the filenames of selfcal images
    """
    selfcal_dir = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name)
    if os.path.exists(selfcal_dir):
        selfcal_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[01]2-MFS-image.fits'))
        tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22_iter*-MFS-image.fits'))
        if len(tec_iter_images) == 0:
            tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22-MFS-image.fits'))
        selfcal_images += tec_iter_images
        selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[3]2-MFS-image.fits'))
        selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image42_iter*-MFS-image.fits'))
        if len(selfcal_images) == 0:
            selfcal_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[01]2-image.fits'))
            tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22_iter*-image.fits'))
            if len(tec_iter_images) == 0:
                tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22-image.fits'))
            selfcal_images += tec_iter_images
            selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[3]2-image.fits'))
            selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image42_iter*-image.fits'))
        selfcal_images.sort()
    else:
        selfcal_images = []

    return selfcal_images


def find_selfcal_tec_plots(direction):
    """
    Returns the filenames of selfcal TEC plots
    """
    selfcal_dir = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name)
    facetpeel_dir = os.path.join(direction.working_dir, 'results', 'facetpeel',
        direction.name)
    peel_dir = os.path.join(direction.working_dir, 'results', 'outlierpeel',
        direction.name)
    dirs = [selfcal_dir, facetpeel_dir, peel_dir]

    # Find most recently modified directory (if any)
    mtimes = []
    for d in dirs:
        if os.path.exists(d):
            mtimes.append(os.path.getmtime(d))
        else:
            mtimes.append(np.nan)
    try:
        latest_dir = dirs[np.nanargmax(mtimes)]
    except (ValueError, TypeError):
        # ValueError or TypeError indicates mtimes list is all NaNs
        return []

    selfcal_plots = glob.glob(os.path.join(latest_dir, '*.make_selfcal_plots_tec*.png'))
    selfcal_plots.sort()

    return selfcal_plots


def find_selfcal_gain_plots(direction):
    """
    Returns the filenames of selfcal Gain plots
    """
    selfcal_dir = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name)
    facetpeel_dir = os.path.join(direction.working_dir, 'results', 'facetpeel',
        direction.name)
    peel_dir = os.path.join(direction.working_dir, 'results', 'outlierpeel',
        direction.name)
    dirs = [selfcal_dir, facetpeel_dir, peel_dir]

    # Find most recently modified directory (if any)
    mtimes = []
    for d in dirs:
        if os.path.exists(d):
            mtimes.append(os.path.getmtime(d))
        else:
            mtimes.append(np.nan)
    try:
        latest_dir = dirs[np.nanargmax(mtimes)]
    except (ValueError, TypeError):
        # ValueError or TypeError indicates mtimes list is all NaNs
        return []

    selfcal_plots = glob.glob(os.path.join(latest_dir, '*.make_selfcal_plots_amp*.png'))
    selfcal_plots.extend(glob.glob(os.path.join(latest_dir, '*.make_selfcal_plots_phase*.png')))
    selfcal_plots.sort()

    return selfcal_plots


def find_facet_images(direction):
    """
    Returns the filenames and op names of full facet images
    """
    if direction.name == 'field':
        mosaic_dir = os.path.join(direction.working_dir, 'results', 'fieldmosaic*',
            direction.name)
        field_images = glob.glob(os.path.join(mosaic_dir, '*.correct_mosaic.pbcut.fits'))
        fieldmosaic_ops = []
        for field_image in field_images:
            trimed_name = field_image.split('results/fieldmosaic')[1]
            fieldmosaic_ops.append('fieldmosaic'+trimed_name.split('/')[0])
        return field_images, fieldmosaic_ops

    selfcal_dir = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name)
    image_dir = os.path.join(direction.working_dir, 'results', 'facetimage*',
        direction.name)
    peelimage_dir = os.path.join(direction.working_dir, 'results', 'facetpeel',
        direction.name)
    dirs = [selfcal_dir, image_dir, peelimage_dir]

    # Search for various image patterns
    facet_images = []
    for d in dirs:
        facet_images += glob.glob(os.path.join(d, '*.wsclean_image_full-MFS-image.fits'))
        facet_images += glob.glob(os.path.join(d, '*.wsclean_image_full-image.fits'))
        facet_images += glob.glob(os.path.join(d, '*.wsclean_image_full2-MFS-image.fits'))
        facet_images += glob.glob(os.path.join(d, '*.wsclean_image_full2-image.fits'))

    facetimage_ops = []
    for facet_image in facet_images:
        trimed_name = facet_image.split('results/facet')[1]
        facetimage_ops.append('facet'+trimed_name.split('/')[0])

    return facet_images, facetimage_ops


def find_facet_verify_images(direction):
    """
    Returns the filenames and op names of full facet images
    """

    selfcal_dir = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name)
    peelimage_dir = os.path.join(direction.working_dir, 'results', 'facetpeel',
        direction.name)
    dirs = [selfcal_dir, peelimage_dir]

    # Search for various image patterns
    facet_verify_images = []
    for d in dirs:
        facet_verify_images += glob.glob(os.path.join(d, '*.wsclean_pre-image.fits'))
        facet_verify_images += glob.glob(os.path.join(d, '*.wsclean_post-image.fits'))


    return facet_verify_images

def get_current_step(direction):
    """
    Returns name and index of current step, total number of steps, and start time
    of current operation
    """
    current_op = get_current_op(direction)
    if current_op is None:
        return (None, None, None, None)

    statefile = os.path.join(direction.working_dir, 'results', current_op,
        direction.name, 'statefile')
    if os.path.exists(statefile):
        try:
            f = open(statefile, 'r')
            d = pickle.load(f)
            f.close()
        except (EOFError, ValueError):
            # Catch errors related to the statefile being written to by the
            # pipeline when we're trying to read from it
            return (None, None, None, None)
    else:
        return (None, None, None, None)

    # Get the last step in the statefile (the previous step to the current one)
    # and use it to determine the current step. This won't work quite right for
    # loops (if the previous step was the last step of the loop, we will get the
    # next step after the loop instead of the first step in the loop if it is
    # still looping), but is the best we can do currently
    found_prev = False
    prev_indx = -1
    current_steps = get_current_op_step_names(direction)
    while not found_prev:
        # Work backward to find a valid step (i.e., not a plugin step)
        previous_step_name = os.path.basename(d[1][prev_indx][1]['ok.mapfile']).split('.ok.mapfile')[0]
        if previous_step_name in current_steps:
            found_prev = True
        else:
            prev_indx -= 1
            if abs(prev_indx) > len(d[1]):
                return (None, None, None, None)
    try:
        current_index = min(len(current_steps)-1, current_steps.index(previous_step_name)+1)
    except ValueError:
        return (None,None,None,None)

    # Get start time from statefile and check for newer one in the logs directory
    # (since the statefile is not updated until at least one step is completed)
    start_time = d[0]['start_time']
    logdir = os.path.join(direction.working_dir, 'results', current_op,
        direction.name, 'logs')
    dirs = glob.glob(logdir + '/*')
    mtimes = []
    for d in dirs:
        if os.path.exists(d):
            mtimes.append(os.path.getmtime(d))
        else:
            mtimes.append(np.nan)
    try:
        latest_dir = dirs[np.nanargmax(mtimes)]
        start_time = os.path.basename(latest_dir)
    except (ValueError, TypeError):
        # ValueError or TypeError indicates mtimes list is all NaNs
        pass

    return (current_steps[current_index], current_index, len(current_steps), start_time)


def check_for_error(direction, start_time):
    """
    Returns True if pipeline log indicates an error
    """
    current_op = get_current_op(direction)
    if current_op is None or start_time is None:
        return False

    logfile = os.path.join(direction.working_dir, 'results', current_op,
        direction.name, 'logs', start_time, 'pipeline.log')
    if os.path.exists(logfile):
        try:
            with open(logfile, "rb") as f:
                first = f.readline()      # Read the first line.
                f.seek(-2, 2)             # Jump to the second last byte.
                while f.read(1) != b"\n": # Until EOL is found...
                    f.seek(-2, 1)         # ...jump back the read byte plus one more.
                last = f.readline()       # Read last line.

                if ('Processing interrupted: shutting down' in last or
                    'completed with errors' in last):
                    return True
                else:
                    return False
        except (EOFError, ValueError):
            # Catch errors related to the statefile being written to by the
            # pipeline when we're trying to read from it
            return False
    else:
        return False


def get_current_op_step_names(direction):
    """
    Returns lits of step names for current operation
    """
    current_op = get_current_op(direction)
    parset_file = os.path.join(direction.working_dir, 'results', current_op,
        direction.name, 'pipeline.parset')
    parset = Parset()
    parset.adoptFile(parset_file)
    pipeline_args = parset.makeSubset(parset.fullModuleName('pipeline') + '.')
    step_name_list = pipeline_args.getStringVector('steps')

    # Filter out plugin steps
    filter_step_name_list = []
    for stepname in step_name_list:
        fullparset = parset.makeSubset(parset.fullModuleName(str(stepname)) + '.')
        subparset = fullparset.makeSubset(fullparset.fullModuleName('control') + '.')
        try:
            kind_of_step = subparset.getString('kind')
        except:
            kind_of_step = 'recipe'
        if kind_of_step != 'plugin':
            if kind_of_step == 'loop':
                loopsteps = subparset.getStringVector('loopsteps')
                for loopstep in loopsteps:
                    fullparset_loop = parset.makeSubset(parset.fullModuleName(str(loopstep)) + '.')
                    subparset_loop = fullparset_loop.makeSubset(fullparset_loop.fullModuleName('control') + '.')
                    try:
                        kind_of_loop_step = subparset_loop.getString('kind')
                    except:
                        kind_of_loop_step = 'recipe'
                    if kind_of_loop_step != 'plugin':
                        filter_step_name_list.append(loopstep)
            else:
                filter_step_name_list.append(stepname)

    return filter_step_name_list


def formatCoord(x, y):
    """Custom coordinate format"""
    global midRA, midDec

    RA, Dec = factor.directions.xy2radec([x], [y], midRA, midDec)
    RA_str = Angle(RA[0], unit='deg').to_string('hour')
    Dec_str = Angle(Dec[0], unit='deg').to_string('deg')
    return 'RA = {0} Dec = {1}'.format(RA_str, Dec_str)


def read_vertices(filename):
    """
    Returns facet vertices
    """
    with open(filename, 'r') as f:
        direction_dict = pickle.load(f)
    return direction_dict['vertices']


def verify_subtract(direction):
    """
    Checks selfcal success
    """
    verify_subtract_mapfile = os.path.join(direction.working_dir, 'results', 'facetselfcal',
        direction.name, 'mapfiles', 'verify_subtract.break.mapfile')
    if os.path.exists(verify_subtract_mapfile):
        ok_mapfile = DataMap.load(verify_subtract_mapfile)
        ok_flags = [ast.literal_eval(item.file) for item in ok_mapfile]
        if all(ok_flags):
            return True
        else:
            return False
    else:
        return False


def wrap(text, width=60):
    """Wraps text to given width and returns list of lines."""
    lines = []
    for paragraph in text.split('\n'):
        line = []
        len_line = 0
        for word in paragraph.split(' '):
            word.strip()
            len_word = len(word)
            if len_line + len_word <= width:
                line.append(word)
                len_line += len_word + 1
            else:
                lines.append(' '.join(line))
                line = [word]
                len_line = len_word + 1
        lines.append(' '.join(line))
    return lines
