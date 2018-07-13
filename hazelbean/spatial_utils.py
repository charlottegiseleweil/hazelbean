import os, sys, shutil, random, math, atexit, time
from collections import OrderedDict
import functools
from functools import reduce
from osgeo import gdal, osr, ogr
import numpy as np
import random
import multiprocessing
import multiprocessing.pool
import hazelbean as hb
import scipy
import geopandas as gpd
import warnings

# Conditional imports
try:
    import geoecon as ge
except:
    ge = None

numpy = np
L = hb.get_logger('hb spatial_utils')

import hazelbean as hb



def zonal_statistics_rasterized(zones_path_or_array, values_path_or_array, zones_ndv=None, values_ndv=None, zones_dtype=None, values_dtype=None):
    """
    Calculate zonal statistics using a pre-generated raster ID array.

    :param zones_array:
    :param values_array:
    :param zones_ndv:
    :param values_ndv:
    :return:
    """

    if type(zones_path_or_array) is str:
        if not zones_dtype:
            zones_dtype = hb.get_datatype_from_uri(zones_path_or_array)
        if not zones_ndv:
            zones_ndv = hb.get_nodata_from_uri(zones_path_or_array)
            if zones_ndv is None:
                zones_ndv = hb.default_no_data_values_by_gdal_number[zones_dtype]
        zones_array = hb.as_array(values_path_or_array).astype(hb.gdal_number_to_numpy_type[values_dtype])

    elif type(zones_path_or_array) is np.ndarray:
        zones_dtype = hb.numpy_type_to_gdal_number[zones_path_or_array.dtype]
        zones_ndv = hb.default_no_data_values_by_gdal_number[zones_dtype]
        zones_array = zones_path_or_array.astype(hb.gdal_number_to_numpy_type[zones_dtype])

    else:
        raise TypeError('Unknown array type given to zones_path_or_array')

    if type(values_path_or_array) is str:
        if not values_dtype:
            values_dtype = hb.get_datatype_from_uri(values_path_or_array)
        if not values_ndv:
            values_ndv = hb.get_nodata_from_uri(values_path_or_array)
            if values_ndv is None:
                values_ndv = hb.default_no_data_values_by_gdal_number[values_dtype]
        values_array = hb.as_array(values_path_or_array).astype(hb.gdal_number_to_numpy_type[values_dtype])

    elif type(values_path_or_array) is np.ndarray:
        values_dtype = hb.numpy_type_to_gdal_number[values_path_or_array.dtype]
        values_ndv = hb.default_no_data_values_by_gdal_number[values_dtype]
        values_array = values_path_or_array.astype(hb.gdal_number_to_numpy_type[values_dtype])

    else:
        raise TypeError('Unknown array type given to values_path_or_array')

    if zones_path_or_array.shape != values_path_or_array.shape:
        raise NameError('The zones array size is not the same as the values array. Zones: ' + str(zones_array.shape) + ' Values: ' + str(values_array.shape))

    if values_dtype <= 5:
        unique_ids, sums, counts = hb.zonal_stats_32bit_int_values(zones_array, values_array, zones_ndv, values_ndv)
    elif values_dtype == 6:
        unique_ids, sums, counts = hb.zonal_stats_32bit_float_values(zones_array, values_array, zones_ndv, values_ndv)
    elif values_dtype == 7:
        # Concurrency problem here? One solution: put pauses before and after cython calls? that seems horrible.
        unique_ids, sums, counts = hb.zonal_stats_64bit_float_values(zones_array, values_array, zones_ndv, values_ndv)
    else:
        raise TypeError('data type of values not understood.')

    zones_path_or_array = None
    values_path_or_array = None
    zones_array = None
    values_array = None

    # 52 is 4464.

    return unique_ids, sums, counts


def create_gdal_virtual_raster(input_tifs_uri_list, ouput_virt_uri, srcnodata=None, shifted_extent=None):
    gdal_command = 'gdalbuildvrt '
    if srcnodata:
        gdal_command += '-srcnodata ' + str(srcnodata) + ' '
    if shifted_extent:
        gdal_command += '-a_srs EPSG:4326 -te ' + shifted_extent[0] + ' ' + shifted_extent[1] + ' ' + shifted_extent[
            2] + ' ' + shifted_extent[3] + ' '
    gdal_command += ouput_virt_uri + ' '
    for tif_uri in input_tifs_uri_list:
        gdal_command += tif_uri + ' '

    print ('gdal_command', gdal_command)
    os.system(gdal_command)




def create_gdal_virtual_raster_using_file(file_paths_list, output_tif_path, extent_shift_match_path=None, remove_generator_files=True, srcnodata=None, dstnodata=None):
    for file_path in file_paths_list:
        assert os.path.exists(file_path)

    virt_file_list_txt_path = os.path.join(os.path.split(output_tif_path)[0], 'virt_file_list.txt')
    with open(virt_file_list_txt_path, 'w') as f:
        for line in file_paths_list:
            f.write(line + '\n')

    gdal_command = 'gdalbuildvrt '
    gdal_command += '-input_file_list ' + virt_file_list_txt_path + ' '

    if srcnodata is not None:
        gdal_command += '-srcnodata ' + str(srcnodata) + ' '

    if extent_shift_match_path:
        shifted_extent = hb.get_raster_info(extent_shift_match_path)['bounding_box']
        gdal_command += '-a_srs EPSG:4326 -te ' + str(shifted_extent[0]) + ' '  + str(shifted_extent[1]) + ' ' + str(shifted_extent[2]) + ' ' + str(shifted_extent[3]) + ' '

    temporary_virt_filename = output_tif_path.replace('.tif', '.vrt')

    gdal_command += temporary_virt_filename

    L.info('Running external gdal command: ' + gdal_command)
    os.system(gdal_command)

    if srcnodata is None:
        srcnodata = hb.get_nodata_from_uri(file_paths_list[0])
    if dstnodata is None:
        dstnodata = hb.get_nodata_from_uri(file_paths_list[0])

    gdal_command = 'gdalwarp -overwrite ' + temporary_virt_filename + ' ' + output_tif_path + ' -srcnodata ' + str(srcnodata) + ' -dstnodata ' + str(dstnodata)

    L.info('Running external gdal command: ' + gdal_command)

    os.system(gdal_command)

    if remove_generator_files:
        hb.remove_at_exit(virt_file_list_txt_path)
        hb.remove_at_exit(temporary_virt_filename)




def set_ndv_by_mask_path(input_data_path, valid_mask_path, output_path=None, ndv=None):
    # NOTE Memory safe.
    if not output_path:
        ds = gdal.OpenEx(input_data_path, gdal.GA_Update)
        band = ds.GetRasterBand(1)
        array = band.ReadAsArray()

        if not ndv:
            ndv = hb.get_nodata_from_uri(input_data_path)

        valid_array = hb.as_array(valid_mask_path)

        masked_array = np.where(valid_array==1, array, ndv)

        band.WriteArray(masked_array)

        band = None
        ds = None
    else:
        ds = gdal.OpenEx(input_data_path, gdal.GA_Update)
        band = ds.GetRasterBand(1)
        array = band.ReadAsArray()
        if not ndv:
            ndv = hb.get_nodata_from_uri(input_data_path)
        valid_array = hb.as_array(valid_mask_path)
        masked_array = np.where(valid_array == 1, array, ndv)
        band = None
        ds = None

        hb.save_array_as_geotiff(masked_array, output_path, input_data_path, no_data_value_override=ndv, data_type_override=hb.get_datatype_from_uri(input_data_path))







def create_valid_mask_from_vector_path(input_vector_path, match_raster_path, output_raster_path, all_touched=False):

    band_nodata_list = [0]
    datatype = 1
    hb.new_raster_from_base_pgp06(match_raster_path, output_raster_path, datatype, band_nodata_list)
    burn_values = [1]
    option_list = []
    if all_touched:
        option_list.append("ALL_TOUCHED=TRUE")
    hb.rasterize(input_vector_path, output_raster_path, burn_values, option_list, layer_index=0)




def clip_raster_by_vector(input_path, output_path, clip_vector_path, resample_method='nearest',
                           output_data_type=None, nodata_target=None, all_touched=False, verbose=False, ensure_fits=False,
                           gtiff_creation_options=hb.DEFAULT_GTIFF_CREATION_OPTIONS):
    base_raster_path_list = [input_path]
    clip_temp_path = hb.temp('.tif', 'clip_temp', True)
    target_raster_path_list = [clip_temp_path]
    resample_method_list = [resample_method]

    # NOTE Here we restrict this to the same pixelsize as the input, so it won't actually reproject I BELIEVE
    target_pixel_size = hb.get_raster_info(input_path)['pixel_size']
    bounding_box_mode = 'intersection'
    base_vector_path_list = [clip_vector_path]
    raster_align_index = 0

    hb.align_and_resize_raster_stack(base_raster_path_list, target_raster_path_list, resample_method_list,
                                     target_pixel_size, bounding_box_mode, base_vector_path_list=base_vector_path_list,
                                     raster_align_index=raster_align_index, ensure_fits=ensure_fits, all_touched=all_touched,
                                     gtiff_creation_options=gtiff_creation_options)

    # Mask out areas outside vector
    # NOTE that the all-touched parameter is only used here. It may be worthwhile to move this above the align call to solve off by one errors.
    mask_temp_path = hb.temp('.tif', 'mask_temp', True)
    hb.create_valid_mask_from_vector_path(clip_vector_path, clip_temp_path, mask_temp_path, all_touched=all_touched)

    def apply_mask(valid, values):
        chunk = np.where(valid == 1.0, values, nodata_target)
        return chunk

    base_raster_path_band_list = [(mask_temp_path, 1), (clip_temp_path, 1)]

    if not output_data_type:
        output_data_type = hb.get_datatype_from_uri(input_path)

    if not nodata_target:
        nodata_target = hb.get_nodata_from_uri(input_path)
    if nodata_target == 0 or not nodata_target:
        nodata_target = hb.default_no_data_values_by_gdal_number[output_data_type]

    hb.raster_calculator(
        base_raster_path_band_list, apply_mask, output_path,
        output_data_type, nodata_target)



def clip_while_aligning_to_coarser(input_path, output_path, clip_vector_path, coarser_path, resample_method='nearest',
                           output_data_type=None, nodata_target=None, all_touched=False, verbose=False, ensure_fits=False, gtiff_creation_options=hb.DEFAULT_GTIFF_CREATION_OPTIONS):
    base_raster_path_list = [coarser_path, input_path]
    clip_temp_path1 = hb.temp('.tif', 'clip_temp1', remove_at_exit=True)
    clip_temp_path2 = hb.temp('.tif', 'clip_temp2', remove_at_exit=True)
    target_raster_path_list = [clip_temp_path1, clip_temp_path2]
    resample_method_list = [resample_method, resample_method]

    # NOTE Here we restrict this to the same pixelsize as the input, so it won't actually reproject I BELIEVE
    target_pixel_size = hb.get_raster_info(input_path)['pixel_size']
    bounding_box_mode = hb.get_raster_info(coarser_path)['bounding_box']
    base_vector_path_list = [clip_vector_path]
    raster_align_index = 0



    hb.align_and_resize_raster_stack(base_raster_path_list, target_raster_path_list, resample_method_list,
                                     target_pixel_size, bounding_box_mode, base_vector_path_list=base_vector_path_list,
                                     raster_align_index=raster_align_index, ensure_fits=ensure_fits, all_touched=all_touched,
                                     gtiff_creation_options=gtiff_creation_options)

    # Mask out areas outside vector
    mask_temp_path = hb.temp('.tif', 'mask_temp', True)
    hb.create_valid_mask_from_vector_path(clip_vector_path, clip_temp_path2, mask_temp_path)

    def apply_mask(valid, values):
        chunk = np.where(valid == 1.0, values, nodata_target)
        return chunk

    base_raster_path_band_list = [(mask_temp_path, 1), (clip_temp_path2, 1)]

    if not output_data_type:
        output_data_type = hb.get_datatype_from_uri(input_path)

    if not nodata_target:
        nodata_target = hb.get_nodata_from_uri(input_path)
    if nodata_target == 0 or not nodata_target:
        nodata_target = hb.default_no_data_values_by_gdal_number[output_data_type]

    hb.raster_calculator(
        base_raster_path_band_list, apply_mask, output_path,
        output_data_type, nodata_target)

def warp_raster_to_match(input_path, output_path, match_path, resample_method, target_bb=None, target_sr_wkt=None, gtiff_creation_options=hb.DEFAULT_GTIFF_CREATION_OPTIONS):

    target_pixel_size = hb.get_cell_size_from_uri(match_path)
    target_bb = hb.get_raster_info(match_path)['bounding_box']
    target_sr_wkt = hb.get_raster_info(match_path)['projection']
    hb.warp_raster(input_path, target_pixel_size, output_path,
            resample_method, target_bb=target_bb, target_sr_wkt=target_sr_wkt,
            gtiff_creation_options=hb.DEFAULT_GTIFF_CREATION_OPTIONS)

def save_array_as_npy(array, output_uri):
    np.save(output_uri, array)

def load_npy_as_array(input_uri, mmap_mode=None):
    return np.load(input_uri, mmap_mode=mmap_mode)

def read_1d_npy_chunk(input_path, start_entry, num_entries):
    """
    Reads a SUBSET of a npy file at path where you can specify a starting point and number of entries.
    :param input_path:
    :param start_entry:
    :param num_entries:
    :return:
    """
    with open(input_path, 'rb') as fhandle:
        major, minor = np.lib.format.read_magic(fhandle)
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(fhandle)
        assert not fortran, "Fortran order arrays not supported"
        # Make sure the offsets aren't invalid.
        assert start_entry < shape[0], (
            'start_entry is beyond end of file'
        )
        assert start_entry + num_entries <= shape[0], (
            'start_row + num_rows > shape[0]'
        )
        # Get the number of elements in one 'row' by taking
        # a product over all other dimensions.
        # row_size = np.prod(shape[1:])
        start_byte = start_entry * dtype.itemsize

        # start_byte = start_entry

        fhandle.seek(start_byte, 1)
        # n_items = row_size * num_rows
        flat = np.fromfile(fhandle, count=num_entries, dtype=dtype)
        return flat.reshape((-1,) + shape[1:])

def read_2d_npy_chunk(input_path, start_row, num_rows, max_entries=None):
    """
    Reads a SUBSET of a 2 dimensional npy file at path where you can specify a starting row and number of subsequent rows
    :param input_path:
    :param start_row:
    :param num_rows:
    :param max_entries:
    :return:
    """
    assert start_row >= 0 and num_rows > 0
    with open(input_path, 'rb') as fhandle:
        major, minor = numpy.lib.format.read_magic(fhandle)
        shape, fortran, dtype = numpy.lib.format.read_array_header_1_0(fhandle)
        assert not fortran, "Fortran order arrays not supported"
        # Make sure the offsets aren't invalid.
        assert start_row < shape[0], (
            'start_row is beyond end of file'
        )
        assert start_row + num_rows <= shape[0], (
            'start_row + num_rows > shape[0]'
        )
        # Get the number of elements in one 'row' by taking
        # a product over all other dimensions.
        row_size = numpy.prod(shape[1:])
        start_byte = start_row * row_size * dtype.itemsize
        fhandle.seek(start_byte, 1)
        n_items = row_size * num_rows
        if n_items > max_entries:
            n_items = max_entries
        flat = numpy.fromfile(fhandle, count=n_items, dtype=dtype)

        # NOTE: Reshaping was a bit funny  here because the 2d version of this funciton is purpose built for the gdra project. Need to generalize.
        return flat.reshape((1,) + (-1,))
        # return flat.reshape((-1,) + (1,))
        # return flat.reshape((-1,) + shape[1:])


def read_3d_npy_chunk(input_path, d1_index, d2_index, d3_start, d3_end):
    """
    Reads a SUBSET of a 3-dimensional npy file at path where you can specify the index for dimensions 1 and 2,
    and then give a range of values for d3. This works well when, for instance, you have multiple lists of 2-dim
    coordinates, where each list is ranked by value.

    :param input_path:
    :param d1_index:
    :param d2_index:
    :param d3_start:
    :param d3_end:
    :return:
    """
    with open(input_path, 'rb') as fhandle:
        major, minor = numpy.lib.format.read_magic(fhandle)
        shape, fortran, dtype = numpy.lib.format.read_array_header_1_0(fhandle)

        row_size = shape[2]
        n_items = d3_end - d3_start
        start_byte = ((d1_index) * 2 + d2_index) * row_size * dtype.itemsize
        fhandle.seek(start_byte, 1)


        flat = numpy.fromfile(fhandle, count=n_items, dtype=dtype)

        return flat.reshape(1, 1, n_items)




def save_array_as_geotiff(array, out_uri, geotiff_uri_to_match=None, ds_to_match=None, band_to_match=None,
                          optimize_data_type=True, data_type_override=None, no_data_value_override=None,
                          geotransform_override=None, projection_override=None, n_cols_override=None,
                          n_rows_override=None, compress=False, compression_method=None,
                          verbose=None, set_inf_to_no_data_value=False,
                          save_png=False):
    '''
    Saves an array as a geotiff at uri_out. Attempts to correctly deal with many possible data flaws, such as
    assigning a datatype to the geotiff that matches the required pixel depth. Also determines the best (according to me)
    no_data_value to use based on the dtype and range of the data
    '''
    execute_in_python = True

    n_cols = array.shape[1]
    n_rows = array.shape[0]
    geotransform = None
    projection = None
    data_type = None
    no_data_value = None

    if geotiff_uri_to_match != None:
        ds_to_match = gdal.Open(geotiff_uri_to_match)
        band_to_match = ds_to_match.GetRasterBand(1)

    # ideally, the function is passed a gdal dataset (ds) and the gdal band.
    if ds_to_match and band_to_match:
        n_cols = ds_to_match.RasterXSize
        n_rows = ds_to_match.RasterYSize
        data_type = band_to_match.DataType
        no_data_value = band_to_match.GetNoDataValue()
        geotransform = ds_to_match.GetGeoTransform()
        projection = ds_to_match.GetProjection()

    # Determine optimal data type and no_data_value. Note that it is best to calculate this anew to avoid inheriting a
    # too-small data type that clips data, and thus optimize_data_type is true by default.
    if optimize_data_type and False: # TODOO Deactivated optimize_data_type due to unexpected crashes
        pass
        # temp_data_type, temp_no_data_value = determine_optimal_data_type_and_no_data_value(array)
        # if data_type_override:
        #     if temp_data_type == data_type_override:
        #         data_type = data_type_override
        #     else:
        #         warnings.warn('You specified an data_type_override but its not the same as the optimized data_type. Ensure this is correct')
        #         data_type = data_type_override
        # else:
        #     data_type = temp_data_type
        # if no_data_value_override:
        #     if temp_no_data_value == no_data_value_override:
        #         no_data_value = no_data_value_override
        #     else:
        #         warnings.warn('You specified an no_data_value_override but its not the same as the optimized no_data_value. Ensure this is correct')
        #         no_data_value = no_data_value_override
        # else:
        #     no_data_value = temp_no_data_value
    elif data_type_override is not None or no_data_value_override is not None:
        if data_type_override is not None:
            data_type = data_type_override
        else:
            data_type = 7  # set to largest bitsize
        if no_data_value_override is not None:
            no_data_value = no_data_value_override
        else:
            no_data_value = 9223372036854775807
    else:
        data_type = 6
        no_data_value = -9999

    if not data_type:
        data_type = 7

    # if hb.numpy_type_to_gdal_number[array.dtype] != data_type:
    #     array = array.astype(hb.gdal_number_to_numpy_type[data_type])

    array = array.astype(hb.gdal_number_to_numpy_type[data_type])

    if geotransform_override:
        if type(geotransform_override) is str:
            geotransform = hb.config.common_geotransforms[geotransform_override]
        else:
            geotransform = geotransform_override

    if not geotransform:
        raise NameError('You must have a geotransform set, either in the geotiff_to_match, or manually as a 6-long list. '
                        'e.g. geotransform = (-180.0, 0.08333333333333333, 0.0, 90.0, 0.0, -0.08333333333333333) to '
                        'set to global extent with 5min cells or via a common keyword (defined in config).')

    if geotransform_override:
        if type(geotransform_override) is str:
            geotransform = hb.config.common_geotransforms[geotransform_override]
        else:
            geotransform = geotransform_override

    if projection_override:
        if type(projection_override) is str:
            if projection_override in hb.common_epsg_codes_by_name:
                projection_override = hb.common_epsg_codes_by_name[projection_override]
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(int(projection_override))
                projection = srs.ExportToWkt()
            else:
                projection = projection_override # assume then it alreaydy was a wkt

        else:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(int(projection_override))
            projection = srs.ExportToWkt()

    if n_cols_override:
        n_cols = n_cols_override
    if n_rows_override:
        n_rows = n_rows_override

    if not projection:
        raise NameError('You must have a projection set, either in the geotiff_to_match, or manually via projection_override')

    # Process out_uri
    folder_uri, filename = os.path.split(out_uri)
    basename, file_extension = os.path.splitext(filename)
    if file_extension != '.tif':
        file_extension = '.tif'
        # L.info('No file_extension specified. Assuming .tif.')
    if os.path.exists(folder_uri) or not folder_uri:
        'Everything is fine.'
    elif geotiff_uri_to_match:
        print ('Folder did not exist, assuming you want the same as the geotiff_uri_to_match.')
        folder_uri = os.path.split(geotiff_uri_to_match)[0]
        if not os.path.exists(folder_uri):
            raise NameError('Folder in geotiff_uri_to_match did not exist.')
    else:
        try:
            os.mkdir(folder_uri)
        except:
            raise NameError('Not able to create required folder for ' + folder_uri)

    processed_out_uri = os.path.join(folder_uri, basename + file_extension)

    dst_options = ['BIGTIFF=IF_SAFER', 'TILED=YES']

    if compress and not compression_method:
        dst_options.append('COMPRESS=lzw')
        dst_options.append('PREDICTOR=2')

    if compression_method:
        dst_options.append('COMPRESS=' + compression_method)
        if compression_method == 'lzw':
            dst_options.append('PREDICTOR=2')

            # OUTDATED BUT HILARIOUS NOTE: When I compress an image with gdalwarp the result is often many times larger than the original!
            # By default gdalwarp operates on chunks that are not necessarily aligned with the boundaries of the blocks/tiles/strips of the output format, so this might cause repeated compression/decompression of partial blocks, leading to lost space in the output format.
            # Another possibility is to use gdalwarp without compression and then follow up with gdal_translate with compression:




    if set_inf_to_no_data_value:
        array[(array==np.inf) | (np.isneginf(array))] = no_data_value

    if execute_in_python:
        driver = gdal.GetDriverByName('GTiff')
        dst_ds = driver.Create(processed_out_uri, n_cols, n_rows, 1, data_type, dst_options)
        dst_ds.SetGeoTransform(geotransform)
        dst_ds.SetProjection(projection)
        dst_ds.GetRasterBand(1).SetNoDataValue(no_data_value)
        dst_ds.GetRasterBand(1).WriteArray(array)
    # else:
    #     command_line_gdal_translate(array, processed_out_uri, tiled=True, compression_method=compression_method)


    if not os.path.exists(processed_out_uri):
        raise NameError('Failed to create geotiff ' + processed_out_uri + '.')

    if verbose:
        print ('nyi 1293939202')
        # print ('Saved ' + processed_out_uri + ' which had stats: ' + desc(array))

    if save_png:
        if not ge:
            raise NameError('No plotting interface configured.')
        ge.show_array(array, output_uri=processed_out_uri.replace('.tif', '.png'), cbar_percentiles=[0,50,100])

def extract_features_in_shapefile_by_attribute(input_shp_uri, output_shp_uri, column_name, column_filter):
    gdf = gpd.read_file(input_shp_uri)
    gdf_out = gdf.loc[gdf[column_name] == column_filter]
    gdf_out.to_file(output_shp_uri)

# def extract_features_in_shapefile_by_attribute(input_shapefile_uri, county_shapefile_uri, id_col, entry):
def extract_features_in_shapefile_by_attribute_ogr(input_shp_uri, output_shp_uri, column_name, column_filter):
    '''
    POSSIBLY DEPRECATED in favor of the geopandas method. Also i broke the code on the way out.

    Creates a new shapefile with only the features that match attribute_filter_string.
    '''
    # L.info('Opening ' + input_shp_uri)
    input_shp = ogr.Open(input_shp_uri)
    input_layer = input_shp.GetLayer(0)
    input_shp = None

    driver = ogr.GetDriverByName('ESRI Shapefile')
    output_shp = driver.CreateDataSource(output_shp_uri)

    output_name = hb.quad_split_path(output_shp_uri)[2]

    # Assumes srs is the same as input.
    srs = input_layer.GetSpatialRef()
    output_layer = output_shp.CreateLayer(output_name, srs, ogr.wkbPolygon)
    input_layer_def = input_layer.GetLayerDefn()
    output_layer_def = output_layer.GetLayerDefn()
    field_count = input_layer_def.GetFieldCount()

    # DO THE FILTERING
    attribute_filter_string = str(column_name) + '=\'' + str(column_filter) + '\''
    input_layer.SetAttributeFilter(str(attribute_filter_string))
    # L.debug('Layer filter ' + str(attribute_filter_string) + ' resulted in ' + str(len(input_layer)) + ' features selected.')

    # Create attribute table columns (fields)
    for field_index in range(field_count):
        input_field = input_layer_def.GetFieldDefn(field_index)
        output_field = ogr.FieldDefn(input_field.GetName(), input_field.GetType())
        output_field.SetWidth(input_field.GetWidth())
        output_field.SetPrecision(input_field.GetPrecision())
        output_layer.CreateField(output_field)

    # Create features
    for input_feature in input_layer:
        geometry = input_feature.GetGeometryRef()
        output_feature = ogr.Feature(input_layer.GetLayerDefn())
        for i in range(0, output_layer_def.GetFieldCount()):
            field_def = output_layer_def.GetFieldDefn(i)
            field_name = field_def.GetName()
            output_feature.SetField(output_layer_def.GetFieldDefn(i).GetNameRef(),
                                    input_feature.GetField(i))
        output_feature.SetGeometry(geometry)
        output_layer.CreateFeature(output_feature)
        output_feature.Destroy()
    output_shp.Destroy()
    input_layer = None # Memory Management
    return



def get_wkt_from_path(input_path):

    path_extension = os.path.splitext(input_path)[1]
    if path_extension in hb.common_gdal_readable_file_extensions:
        return hb.get_dataset_projection_wkt_uri(input_path)
    elif path_extension in hb.possible_shapefile_extensions:
        return hb.get_datasource_projection_wkt_uri(input_path)
    else:
        raise NameError('Unable to get wkt from ' + str(input_path))



def get_shape_from_dataset_path(dataset_path):

    dataset = gdal.Open(dataset_path)
    if dataset == None:
        raise IOError(
            'File not found or not valid dataset type at: %s' % dataset_path)

    shape = (dataset.RasterYSize, dataset.RasterXSize)

    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return shape

def get_attribute_table_columns_from_shapefile(shapefile_path, cols=None):
    gdf = gpd.read_file(shapefile_path)
    if cols:
        to_return = gdf[cols]
        gdf = None
        return to_return
    else:
        to_return = gdf
        gdf = None
        return to_return


def convert_shapefile_to_multiple_shapefiles_by_id(shapefile_path, id_col_name, output_dir, suffix=''):
    id_values = hb.get_attribute_table_columns_from_shapefile(shapefile_path, id_col_name)

    for id_value in id_values:
        aoi_path = os.path.join(output_dir, 'aoi_' + str(id_value) + '.shp')
        hb.extract_features_in_shapefile_by_attribute(shapefile_path, aoi_path, id_col_name, id_value)

def check_list_of_paths_exist(input_list):
    for path in input_list:
        if os.path.exists(path):
            print ('EXISTS: ' + path)
        else:
            print ( 'FAILS TO EXIST: ' + path)

def clip_dataset_uri(
        source_dataset_uri, aoi_datasource_uri, out_dataset_uri, intermediate_reprojection_path=None, process_pool=None,
        assert_datasets_projected=False, all_touched=True):

    warnings.warn('Possibly deprecated. connsider using clip_raster_by_vector')
    """
    This function will clip source_dataset to the bounding box of the
    polygons in aoi_datasource and mask out the values in source_dataset
    outside of the AOI with the nodata values in source_dataset.

    Args:
        source_dataset_uri (string): uri to single band GDAL dataset to clip
        aoi_datasource_uri (string): uri to ogr datasource
        out_dataset_uri (string): path to disk for the clipped datset

    Keyword Args:
        process_pool (?): a process pool for multiprocessing

    Returns:
        nothing

    """
    #NOTE: I have altered the signature of this function compared to the
    # previous one because I want to be able to use vectorize_datasets to clip
    # two sources that are not projected

    #raise NotImplementedError('clip_dataset_uri is not implemented yet')

    # I choose to open up the dataset here because I want to use the
    # calculate_value_not_in_dataset function which requires a datasource. For
    # now I do not want to create a uri version of that function.
    source_dataset = gdal.Open(source_dataset_uri)

    source_dataset_wkt = hb.get_wkt_from_path(source_dataset_uri)
    aoi_datasource_wkt = hb.get_wkt_from_path(aoi_datasource_uri)

    if source_dataset_wkt != aoi_datasource_wkt:
        L.warning('source_dataset_wkt != aoi_datasource_wkt so reprojecting!!!')
        # If the projections are not the same, convert the vector to the input rasters projection, clip with buffer, then reproject
        if not intermediate_reprojection_path:
            intermediate_reprojection_path = hb.temp('.shp', remove_at_exit=True) # Removing shapefiles is tricky cause multiple extensions.
        hb.reproject_datasource_uri(aoi_datasource_uri, source_dataset_wkt, intermediate_reprojection_path)


        aoi_datasource_uri = intermediate_reprojection_path

    band, nodata = hb.extract_band_and_nodata(source_dataset)
    datatype = band.DataType

    if nodata is None:
        nodata = hb.calculate_value_not_in_dataset(source_dataset)

    gdal.Dataset.__swig_destroy__(source_dataset)
    source_dataset = None

    dataset_to_align_index = 0 # NECESSARY Otherwise casues a shift.

    pixel_size = hb.get_cell_size_from_uri(source_dataset_uri)

    hb.vectorize_datasets(
        [source_dataset_uri], lambda x: x, out_dataset_uri, datatype, nodata,
        pixel_size, 'intersection', aoi_uri=aoi_datasource_uri,
        assert_datasets_projected=assert_datasets_projected,
        dataset_to_align_index=dataset_to_align_index,
        process_pool=process_pool, vectorize_op=False, all_touched=all_touched)



def get_cell_size_from_geotransform_uri(dataset_uri):
    # Assume linear unit is 1 meter and that the geotransofrm is defined in angular units.
    dataset = gdal.Open(dataset_uri)
    srs = osr.SpatialReference()
    srs.SetProjection(dataset.GetProjection())

    if dataset is None:
        raise IOError(
            'File not found or not valid dataset type at: %s' % dataset_uri)
    linear_units = 1.0
    linear_units_from_srs = srs.GetLinearUnits()
    if linear_units_from_srs != linear_units:
        raise NameError('You are attempting to get cellsize from the geotransform, but this data is projected already with a different linear unit than 1.')
    geotransform = dataset.GetGeoTransform()

    # take absolute value since sometimes negative widths/heights
    try:
        numpy.testing.assert_approx_equal(
            abs(geotransform[1]), abs(geotransform[5]))
        size_meters = abs(geotransform[1]) * linear_units
    except AssertionError as e:
        L.warn(e)
        size_meters = (
                              abs(geotransform[1]) + abs(geotransform[5])) / 2.0 * linear_units

    # Close and clean up dataset
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return size_meters

def read_array_chunk_from_disk(array_path, chunk):
    # chunk in gdal notation: ul, ur, nr, nc
    start = time.time()
    xoff, yoff, xsize, ysize = chunk[0], chunk[1], chunk[2], chunk[3]
    ds = gdal.Open(array_path)
    band = ds.GetRasterBand(1)
    array_chunk = band.ReadAsArray( xoff, yoff, xsize, ysize)

    print (start - time.time())


def as_array(uri, return_all_parts = False, verbose = False, band_number=1): #use GDAL to laod uri. By default only returns the array"
    # Simplest function for loading a geotiff as an array. returns only the array by defauls, ignoring the DS and BAND unless return_all_parts = True.
    ds = gdal.Open(uri)
    band = ds.GetRasterBand(band_number)
    try:
        array = band.ReadAsArray()
    except:
        warnings.warn('Failed to load all of the array. It may be too big for memory.')
        array = None

    # Close and clean up dataset
    if return_all_parts:
        return ds, band, array
    else:
        band = None
        gdal.Dataset.__swig_destroy__(ds)
        ds = None
        return array

def as_array_resampled_to_size(uri, max_size=200000, return_all_parts=False, verbose=False):
    # Use gdal ReadAsArray to only resample to a small enough raster.
    # This is faster than numpy approaches because it uses the band method to only selectively read from disk.
    # HOWEVER, i think there is a huge performance hit if the raster is compressed.
    ds = gdal.Open(uri)
    band = ds.GetRasterBand(1)
    cols = ds.RasterXSize
    rows = ds.RasterYSize
    size = cols * rows

    if size > max_size:
        scale_factor = float(max_size) / float(size)
        render_cols = int(cols * scale_factor**0.5)
        render_rows = int(rows * scale_factor**0.5)
        array = band.ReadAsArray(0, 0, cols, rows, render_cols, render_rows)
    else:
        array = band.ReadAsArray()

    # Close and clean up dataset
    if return_all_parts:
        return ds, band, array
    else:
        band = None
        gdal.Dataset.__swig_destroy__(ds)
        ds = None

    return array


def enumerate_array_as_odict(input_array):
    # TODOO is duplicitive with unique_raster_values?
    values, counts = np.unique(input_array, return_counts=True)

    output = OrderedDict()
    if len(values) > 30:
        # L.debug('enumerate_array_as_odict has more than 30 unique values. Presented only are 100 RANDOM values.')

        for i in random.sample(range(0, len(values) - 1), 30):
            output[values[i]] = counts[i]
    else:
        for i in range(len(values)):
            output[values[i]] = counts[i]

    return output

def enumerate_array_as_histogram(input_array):

    hist = np.histogram(input_array)

    to_return = []
    for i in range(len(hist[0])):
        to_return.append(str(hist[1][i]) + ' to ' + str(hist[1][i+1]) + ': ' + str(hist[0][i]))
    return to_return

def reproject_datasource_uri(original_dataset_uri, output_wkt, output_uri):
    """
    URI wrapper for reproject_datasource that takes in the uri for the
    datasource that is to be projected instead of the datasource itself.
    This function directly calls reproject_datasource.

    Args:
        original_dataset_uri (string): a uri to an ogr datasource
        output_wkt (?): the desired projection as Well Known Text
            (by layer.GetSpatialRef().ExportToWkt())
        output_uri (string): the path to where the new shapefile should be
            written to disk.

    Return:
        nothing

    """

    original_dataset = ogr.Open(original_dataset_uri)
    _ = reproject_datasource(original_dataset, output_wkt, output_uri)


def reproject_datasource(original_datasource, output_wkt, output_uri):
    """
    Changes the projection of an ogr datasource by creating a new
    shapefile based on the output_wkt passed in.  The new shapefile
    then copies all the features and fields of the original_datasource
    as its own.

    Args:
        original_datasource (?): an ogr datasource
        output_wkt (?): the desired projection as Well Known Text
            (by layer.GetSpatialRef().ExportToWkt())
        output_uri (string): the filepath to the output shapefile

    Returns:
        output_datasource (?): the reprojected shapefile.
    """
    # if this file already exists, then remove it
    if os.path.isfile(output_uri):
        os.remove(output_uri)

    output_sr = osr.SpatialReference()
    output_sr.ImportFromWkt(output_wkt)

    # create a new shapefile from the orginal_datasource
    output_driver = ogr.GetDriverByName('ESRI Shapefile')
    output_datasource = output_driver.CreateDataSource(output_uri)


    # loop through all the layers in the orginal_datasource
    for original_layer in original_datasource:

        #Get the original_layer definition which holds needed attribute values
        original_layer_dfn = original_layer.GetLayerDefn()

        #Create the new layer for output_datasource using same name and geometry
        #type from original_datasource, but different projection
        output_layer = output_datasource.CreateLayer(
            original_layer_dfn.GetName(), output_sr,
            original_layer_dfn.GetGeomType())

        #Get the number of fields in original_layer
        original_field_count = original_layer_dfn.GetFieldCount()

        #For every field, create a duplicate field and add it to the new
        #shapefiles layer
        for fld_index in range(original_field_count):
            original_field = original_layer_dfn.GetFieldDefn(fld_index)
            output_field = ogr.FieldDefn(
                original_field.GetName(), original_field.GetType())
            output_layer.CreateField(output_field)

        original_layer.ResetReading()

        #Get the spatial reference of the original_layer to use in transforming
        original_sr = original_layer.GetSpatialRef()

        #Create a coordinate transformation
        coord_trans = osr.CoordinateTransformation(original_sr, output_sr)

        #Copy all of the features in original_layer to the new shapefile
        for original_feature in original_layer:
            geom = original_feature.GetGeometryRef()

            #Transform the geometry into a format desired for the new projection
            geom.Transform(coord_trans)

            #Copy original_datasource's feature and set as new shapes feature
            output_feature = ogr.Feature(
                feature_def=output_layer.GetLayerDefn())
            output_feature.SetFrom(original_feature)
            output_feature.SetGeometry(geom)
            #For all the fields in the feature set the field values from the
            #source field
            for fld_index2 in range(output_feature.GetFieldCount()):
                original_field_value = original_feature.GetField(fld_index2)

                # HACK TO fix if string has non ascii characters in it, which apparently can't be handled by OGR.
                if isinstance(original_field_value, str):
                    original_field_value = str(original_field_value.encode('ascii', errors='ignore'))
                output_feature.SetField(fld_index2, original_field_value)

            output_layer.CreateFeature(output_feature)
            output_feature = None

            original_feature = None

        original_layer = None

    return output_datasource


def vectorize_datasets(
        dataset_uri_list, dataset_pixel_op, dataset_out_uri, datatype_out,
        nodata_out, pixel_size_out, bounding_box_mode,
        resample_method_list=None, dataset_to_align_index=None,
        dataset_to_bound_index=None, aoi_uri=None,
        assert_datasets_projected=True, process_pool=None, vectorize_op=True,
        datasets_are_pre_aligned=False, dataset_options=None, all_touched=True):

    """
    This function applies a user defined function across a stack of
    datasets.  It has functionality align the output dataset grid
    with one of the input datasets, output a dataset that is the union
    or intersection of the input dataset bounding boxes, and control
    over the interpolation techniques of the input datasets, if
    necessary.  The datasets in dataset_uri_list must be in the same
    projection; the function will raise an exception if not.

    Args:
        dataset_uri_list (list): a list of file uris that point to files that
            can be opened with gdal.Open.
        dataset_pixel_op (function) a function that must take in as many
            arguments as there are elements in dataset_uri_list.  The arguments
            can be treated as interpolated or actual pixel values from the
            input datasets and the function should calculate the output
            value for that pixel stack.  The function is a parallel
            paradigmn and does not know the spatial position of the
            pixels in question at the time of the call.  If the
            `bounding_box_mode` parameter is "union" then the values
            of input dataset pixels that may be outside their original
            range will be the nodata values of those datasets.  Known
            bug: if dataset_pixel_op does not return a value in some cases
            the output dataset values are undefined even if the function
            does not crash or raise an exception.
        dataset_out_uri (string): the uri of the output dataset.  The
            projection will be the same as the datasets in dataset_uri_list.
        datatype_out (?): the GDAL output type of the output dataset
        nodata_out (?): the nodata value of the output dataset.
        pixel_size_out (?): the pixel size of the output dataset in
            projected coordinates.
        bounding_box_mode (string): one of "union" or "intersection",
            "dataset". If union the output dataset bounding box will be the
            union of the input datasets.  Will be the intersection otherwise.
            An exception is raised if the mode is "intersection" and the
            input datasets have an empty intersection. If dataset it will make
            a bounding box as large as the given dataset, if given
            dataset_to_bound_index must be defined.

    Keyword Args:
        resample_method_list (list): a list of resampling methods
            for each output uri in dataset_out_uri list.  Each element
            must be one of "nearest|bilinear|cubic|cubic_spline|lanczos".
            If None, the default is "nearest" for all input datasets.
        dataset_to_align_index (int): an int that corresponds to the position
            in one of the dataset_uri_lists that, if positive aligns the output
            rasters to fix on the upper left hand corner of the output
            datasets.  If negative, the bounding box aligns the intersection/
            union without adjustment.
        dataset_to_bound_index (?): if mode is "dataset" this indicates which
            dataset should be the output size.
        aoi_uri (string): a URI to an OGR datasource to be used for the
            aoi.  Irrespective of the `mode` input, the aoi will be used
            to intersect the final bounding box.
        assert_datasets_projected (boolean): if True this operation will
            test if any datasets are not projected and raise an exception
            if so.
        process_pool (?): a process pool for multiprocessing
        vectorize_op (boolean): if true the model will try to numpy.vectorize
            dataset_pixel_op.  If dataset_pixel_op is designed to use maximize
            array broadcasting, set this parameter to False, else it may
            inefficiently invoke the function on individual elements.
        datasets_are_pre_aligned (boolean): If this value is set to False
            this operation will first align and interpolate the input datasets
            based on the rules provided in bounding_box_mode,
            resample_method_list, dataset_to_align_index, and
            dataset_to_bound_index, if set to True the input dataset list must
            be aligned, probably by raster_utils.align_dataset_list
        dataset_options (?): this is an argument list that will be
            passed to the GTiff driver.  Useful for blocksizes, compression,
            etc.

    Returns:
        nothing?

    Raises:
        ValueError: invalid input provided

    """
    if type(dataset_uri_list) != list:
        raise ValueError(
            "dataset_uri_list was not passed in as a list, maybe a single "
            "file was passed in?  Here is its value: %s" %
            (str(dataset_uri_list)))

    if aoi_uri == None:
        hb.assert_file_existance(dataset_uri_list)
    else:
        hb.assert_file_existance(dataset_uri_list + [aoi_uri])

    if dataset_out_uri in dataset_uri_list:
        raise ValueError(
            "%s is used as an output file, but it is also an input file "
            "in the input list %s" % (dataset_out_uri, str(dataset_uri_list)))

    # Parse vector creation options for rasterize
    if all_touched:
        option_list = ["ALL_TOUCHED=TRUE"]
    else:
        option_list = []


    #Create a temporary list of filenames whose files delete on the python
    #interpreter exit
    if not datasets_are_pre_aligned:
        #Handle the cases where optional arguments are passed in
        if resample_method_list == None:
            resample_method_list = ["nearest"] * len(dataset_uri_list)
        if dataset_to_align_index == None:
            dataset_to_align_index = -1
        dataset_out_uri_list = [
            hb.temporary_filename(suffix='.tif', remove_at_exit=True) for _ in dataset_uri_list]
        #Align and resample the datasets, then load datasets into a list
        align_dataset_list(
            dataset_uri_list, dataset_out_uri_list, resample_method_list,
            pixel_size_out, bounding_box_mode, dataset_to_align_index,
            dataset_to_bound_index=dataset_to_bound_index,
            aoi_uri=aoi_uri,
            assert_datasets_projected=assert_datasets_projected, option_list=option_list)
        aligned_datasets = [
            gdal.Open(filename, gdal.GA_ReadOnly) for filename in
            dataset_out_uri_list]
    else:
        #otherwise the input datasets are already aligned
        aligned_datasets = [
            gdal.Open(filename, gdal.GA_ReadOnly) for filename in
            dataset_uri_list]

    aligned_bands = [dataset.GetRasterBand(1) for dataset in aligned_datasets]

    n_rows = aligned_datasets[0].RasterYSize
    n_cols = aligned_datasets[0].RasterXSize

    curdir = os.path.split(dataset_out_uri)[0]
    if not os.path.exists(curdir):
        hb.create_directories(curdir)

    output_dataset = hb.new_raster_from_base(
        aligned_datasets[0], dataset_out_uri, 'GTiff', nodata_out, datatype_out,
        dataset_options=dataset_options)
    output_band = output_dataset.GetRasterBand(1)
    block_size = output_band.GetBlockSize()
    #makes sense to get the largest block size possible to reduce the number
    #of expensive readasarray calls
    for current_block_size in [band.GetBlockSize() for band in aligned_bands]:
        if (current_block_size[0] * current_block_size[1] >
                block_size[0] * block_size[1]):
            block_size = current_block_size

    cols_per_block, rows_per_block = block_size[0], block_size[1]
    n_col_blocks = int(math.ceil(n_cols / float(cols_per_block)))
    n_row_blocks = int(math.ceil(n_rows / float(rows_per_block)))

    dataset_blocks = [
        numpy.zeros(
            (rows_per_block, cols_per_block),
            dtype=hb.GDAL_TO_NUMPY_TYPE[band.DataType]) for band in aligned_bands]

    #If there's an AOI, mask it out
    if aoi_uri != None:
        mask_uri = hb.temporary_filename(suffix='.tif', remove_at_exit=True)
        mask_dataset = hb.new_raster_from_base(
            aligned_datasets[0], mask_uri, 'GTiff', 255, gdal.GDT_Byte,
            fill_value=0, dataset_options=dataset_options)
        mask_band = mask_dataset.GetRasterBand(1)
        aoi_datasource = ogr.Open(aoi_uri)
        aoi_layer = aoi_datasource.GetLayer()
        gdal.RasterizeLayer(mask_dataset, [1], aoi_layer, burn_values=[1], options=option_list)
        mask_array = numpy.zeros(
            (rows_per_block, cols_per_block), dtype=numpy.int8)
        aoi_layer = None
        aoi_datasource = None

    #We only want to do this if requested, otherwise we might have a more
    #efficient call if we don't vectorize.
    if vectorize_op:
        L.warn("this call is vectorizing which is deprecated and slow")
        dataset_pixel_op = numpy.vectorize(dataset_pixel_op)

    dataset_blocks = [
        numpy.zeros(
            (rows_per_block, cols_per_block),
            dtype=hb.GDAL_TO_NUMPY_TYPE[band.DataType]) for band in aligned_bands]

    last_time = time.time()

    for row_block_index in range(n_row_blocks):
        row_offset = row_block_index * rows_per_block
        row_block_width = n_rows - row_offset
        if row_block_width > rows_per_block:
            row_block_width = rows_per_block

        for col_block_index in range(n_col_blocks):
            col_offset = col_block_index * cols_per_block
            col_block_width = n_cols - col_offset
            if col_block_width > cols_per_block:
                col_block_width = cols_per_block

            current_time = time.time()
            if current_time - last_time > 5.0:
                L.info(
                    'raster stack calculation approx. %.2f%% complete',
                    ((row_block_index * n_col_blocks + col_block_index) /
                     float(n_row_blocks * n_col_blocks) * 100.0))
                last_time = current_time

            for dataset_index in range(len(aligned_bands)):
                aligned_bands[dataset_index].ReadAsArray(
                    xoff=col_offset, yoff=row_offset, win_xsize=col_block_width,
                    win_ysize=row_block_width,
                    buf_obj=dataset_blocks[dataset_index][0:row_block_width,0:col_block_width])

            out_block = dataset_pixel_op(*dataset_blocks)

            #Mask out the row if there is a mask
            if aoi_uri != None:
                mask_band.ReadAsArray(
                    xoff=col_offset, yoff=row_offset, win_xsize=col_block_width,
                    win_ysize=row_block_width,
                    buf_obj=mask_array[0:row_block_width,0:col_block_width])
                out_block[mask_array == 0] = nodata_out

            output_band.WriteArray(
                out_block[0:row_block_width, 0:col_block_width],
                xoff=col_offset, yoff=row_offset)

    #Making sure the band and dataset is flushed and not in memory before
    #adding stats
    output_band.FlushCache()
    output_band = None
    output_dataset.FlushCache()
    gdal.Dataset.__swig_destroy__(output_dataset)
    output_dataset = None

    #Clean up the files made by temporary file because we had an issue once
    #where I was running the water yield model over 2000 times and it made
    #so many temporary files I ran out of disk space.
    if aoi_uri != None:
        mask_band = None
        gdal.Dataset.__swig_destroy__(mask_dataset)
        mask_dataset = None
        os.remove(mask_uri)
    aligned_bands = None
    for dataset in aligned_datasets:
        gdal.Dataset.__swig_destroy__(dataset)
    aligned_datasets = None
    if not datasets_are_pre_aligned:
        #if they weren't pre-aligned then we have temporary files to remove
        for temp_dataset_uri in dataset_out_uri_list:
            try:
                os.remove(temp_dataset_uri)
            except OSError:
                L.warn("couldn't delete file %s", temp_dataset_uri)
    calculate_raster_stats_uri(dataset_out_uri)




def calculate_raster_stats_uri(dataset_uri):
    """
    Calculates and sets the min, max, stdev, and mean for the bands in
    the raster.

    Args:
        dataset_uri (string): a uri to a GDAL raster dataset that will be
            modified by having its band statistics set

    Returns:
        nothing
    """

    dataset = gdal.Open(dataset_uri, gdal.GA_Update)

    for band_number in range(dataset.RasterCount):
        band = dataset.GetRasterBand(band_number + 1)
        band.ComputeStatistics(False)

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None



def assert_dataset_is_projected(input_uri):
    dataset = gdal.Open(input_uri)
    projection_as_str = dataset.GetProjection()
    dataset_sr = osr.SpatialReference()
    dataset_sr.ImportFromWkt(projection_as_str)
    if dataset_sr.IsProjected():
        return True
    else:
        raise NameError('Dataset ' + input_uri + ' is unprojected.')

def test_dataset_is_projected(input_uri):
    dataset = gdal.Open(input_uri)
    projection_as_str = dataset.GetProjection()
    dataset_sr = osr.SpatialReference()
    dataset_sr.ImportFromWkt(projection_as_str)
    if dataset_sr.IsProjected():
        return True
    else:
        raise False

def new_raster_from_base_uri(base_uri, *args, **kwargs):
    """A wrapper for the function new_raster_from_base that opens up
        the base_uri before passing it to new_raster_from_base.

        base_uri - a URI to a GDAL dataset on disk.

        All other arguments to new_raster_from_base are passed in.

        Returns nothing.
        """
    base_raster = gdal.Open(base_uri)
    if base_raster is None:
        raise IOError("%s not found when opening GDAL raster")
    new_raster = new_raster_from_base(base_raster, *args, **kwargs)

    gdal.Dataset.__swig_destroy__(new_raster)
    gdal.Dataset.__swig_destroy__(base_raster)
    new_raster = None
    base_raster = None



def OLD_new_raster_from_base(
        base, output_uri, gdal_format, nodata, datatype, fill_value=None,
        n_rows=None, n_cols=None, dataset_options=None):
    """Create a new, empty GDAL raster dataset with the spatial references,
        geotranforms of the base GDAL raster dataset.

        base - a the GDAL raster dataset to base output size, and transforms on
        output_uri - a string URI to the new output raster dataset.
        gdal_format - a string representing the GDAL file format of the
            output raster.  See http://gdal.org/formats_list.html for a list
            of available formats.  This parameter expects the format code, such
            as 'GTiff' or 'MEM'
        nodata - a value that will be set as the nodata value for the
            output raster.  Should be the same type as 'datatype'
        datatype - the pixel datatype of the output raster, for example
            gdal.GDT_Float32.  See the following header file for supported
            pixel types:
            http://www.gdal.org/gdal_8h.html#22e22ce0a55036a96f652765793fb7a4
        fill_value - (optional) the value to fill in the raster on creation
        n_rows - (optional) if set makes the resulting raster have n_rows in it
            if not, the number of rows of the outgoing dataset are equal to
            the base.
        n_cols - (optional) similar to n_rows, but for the columns.
        dataset_options - (optional) a list of dataset options that gets
            passed to the gdal creation driver, overrides defaults

        returns a new GDAL raster dataset."""

    #This might be a numpy type coming in, set it to native python type
    try:
        nodata = nodata.item()
    except AttributeError:
        pass

    if n_rows is None:
        n_rows = base.RasterYSize
    if n_cols is None:
        n_cols = base.RasterXSize
    projection = base.GetProjection()
    geotransform = base.GetGeoTransform()
    driver = gdal.GetDriverByName(gdal_format)

    base_band = base.GetRasterBand(1)
    block_size = base_band.GetBlockSize()
    metadata = base_band.GetMetadata('IMAGE_STRUCTURE')
    base_band = None

    if dataset_options == None:
        #make a new list to make sure we aren't ailiasing one passed in
        dataset_options = []
        #first, should it be tiled?  yes if it's not striped
        if block_size[0] != n_cols:
            #just do 256x256 blocks
            dataset_options = [
                'TILED=YES',
                'BLOCKXSIZE=256',
                'BLOCKYSIZE=256',
                'BIGTIFF=IF_SAFER']
        if 'PIXELTYPE' in metadata:
            dataset_options.append('PIXELTYPE=' + metadata['PIXELTYPE'])

    new_raster = driver.Create(
        output_uri.encode('utf-8'), n_cols, n_rows, 1, datatype,
        options=dataset_options)
    new_raster.SetProjection(projection)
    new_raster.SetGeoTransform(geotransform)
    band = new_raster.GetRasterBand(1)

    if nodata is not None:
        band.SetNoDataValue(nodata)
    else:
        L.warn(
            "None is passed in for the nodata value, failed to set any nodata "
            "value for new raster.")

    if fill_value != None:
        band.Fill(fill_value)
    elif nodata is not None:
        band.Fill(nodata)
    band = None

    return new_raster

def merge_bounding_boxes(bb1, bb2, mode):
    """Helper function to merge two bounding boxes through union or
        intersection"""
    less_than_or_equal = lambda x, y: x if x <= y else y
    greater_than = lambda x, y: x if x > y else y

    if mode == "union":
        comparison_ops = [
            less_than_or_equal, greater_than, greater_than,
            less_than_or_equal]
    if mode == "intersection":
        comparison_ops = [
            greater_than, less_than_or_equal, less_than_or_equal,
            greater_than]

    bb_out = [op(x, y) for op, x, y in zip(comparison_ops, bb1, bb2)]
    return bb_out

def get_rank_array_and_keys(input_array, nan_mask=None, highest_first=True, ndv=None):
    # NOTE, i could get a decent performance increase here by masking nans before the sort.
    if ndv is not None and nan_mask is None:
        nan_mask = np.where(input_array==ndv, 1, 0)

    if ndv is None:
        ndv = -9999

    unraveled_keys = np.unravel_index(input_array.argsort(axis=None), dims=input_array.shape)  # returns TWO arrays in a tuple of all the rows, then all the cols keys

    if highest_first:
        sorted_keys = (unraveled_keys[0][::-1], unraveled_keys[1][::-1])#.astype(np.int64)# thus here we need to reverse each seperately
        unraveled_keys = None  # Key memory chokepoint
    else:
        sorted_keys = unraveled_keys.astype(np.int)
        unraveled_keys = None  # Key memory chokepoint

    sorted_keys = np.array(sorted_keys).astype(np.int64)

    if nan_mask is not None:
        nan_mask = nan_mask.astype(np.int64)
        array, keys = hb.get_rank_array_and_keys_from_sorted_keys_with_nan_mask(sorted_keys, nan_mask, ndv)
    else:
        array, keys = hb.get_rank_array_and_keys_from_sorted_keys_no_nan_mask(sorted_keys, input_array.shape[0], input_array.shape[1])
    return array, keys




def rank_array(input_array, nan_mask=None, highest_first=True, ndv=None, clip_below=None, clip_above=None):
    if nan_mask is not None:
        if ndv is not None:
            nan_mask = np.where(input_array==ndv, 1, nan_mask).astype(np.byte)
        else:
            nan_mask = nan_mask.astype(np.byte)
    if clip_below is not None:
        nan_mask = np.where(input_array < clip_below, 1, nan_mask).astype(np.byte)
    if clip_above is not None:
        nan_mask = np.where(input_array > clip_above, 1, nan_mask).astype(np.byte)

    L.info('  Arg sorting to get keys.')
    start1 = time.time()
    if nan_mask is not None:
        keys_where = np.where(nan_mask != 1)
        if highest_first:
            sorted_keys_1dim = input_array[keys_where].argsort(axis=None)[::-1]
        else:
            sorted_keys_1dim = input_array[keys_where].argsort(axis=None)

        sorted_keys = (keys_where[0][sorted_keys_1dim], keys_where[1][sorted_keys_1dim])
    else:
        sorted_keys = np.unravel_index(input_array.argsort(axis=None), dims=input_array.shape)
        L.info('  Extracting keys and/or value and order arrays.')
        if highest_first:
            sorted_keys = np.asarray([sorted_keys[0][::-1], sorted_keys[1][::-1]])

    print ('elapsed time', time.time() - start1)

    return sorted_keys

def get_rank_array(input_array, ignore_value=None, highest_first=True):
    # NOTE Still in array paradigm rather than af paradigm
    # L.debug('Getting sorted keys from array.')
    sorted_keys = get_sorted_keys_of_array(input_array, highest_first=highest_first)

    rank_array = np.zeros(input_array.shape)
    # START THE COUNTER AT 1 so that no_data = zero works.
    rank_counter = 1
    for key in sorted_keys:
        if ignore_value is not None:  # NOTE IS not ==
            if input_array[key] != ignore_value:
                # TODOOO NOTE This could  be heavily cythonized.
                rank_array[key] = rank_counter
                rank_counter += 1
            else:
                rank_array[key] = ignore_value

        else:
            rank_array[key] = rank_counter
            rank_counter += 1

    return rank_array, sorted_keys


def get_rank_of_top_percentile_of_array(percentile, input_array, ignore_value=None, highest_first=True):
    rank_array, sorted_keys = get_rank_array(input_array, ignore_value, highest_first)
    value_at_percentile = np.percentile(rank_array[rank_array != ignore_value], percentile)
    include_keys = np.where(rank_array < value_at_percentile)
    output_array = np.zeros(input_array.shape)
    output_array[include_keys] = rank_array[include_keys]
    return output_array


def get_top_percentile_of_array(percentile, input_array, ignore_value=None, highest_first=True):
    rank_array, sorted_keys = get_rank_array(input_array, ignore_value, highest_first)
    value_at_percentile = np.percentile(rank_array, percentile)
    include_keys = np.where(rank_array < value_at_percentile)
    output_array = np.zeros(input_array.shape)
    output_array[include_keys] = input_array[include_keys]
    return output_array


def get_set_of_top_percentile_of_array(percentile, input_array, ignore_value=None, highest_first=True):
    rank_array, sorted_keys = get_rank_array(input_array, ignore_value, highest_first)
    value_at_percentile = np.percentile(rank_array, percentile)
    include_keys = np.where(rank_array < value_at_percentile)
    output_array = np.zeros(input_array.shape).astype(np.int8)
    output_array[include_keys] = 1
    return output_array
def create_vector_from_raster_extents(input_path, output_path):
    extent = hb.get_bounding_box(input_path)
    hb.create_vector_from_bounding_box(extent, output_path)


def create_vector_from_bounding_box(bounding_box, output_path):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(bounding_box[0], bounding_box[1])
    ring.AddPoint(bounding_box[0], bounding_box[3])
    ring.AddPoint(bounding_box[2], bounding_box[3])
    ring.AddPoint(bounding_box[2], bounding_box[1])
    ring.AddPoint(bounding_box[0], bounding_box[1])
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)

    # Save extent to a new Shapefile
    outDriver = ogr.GetDriverByName("ESRI Shapefile")

    # Remove output shapefile if it already exists
    if os.path.exists(output_path):
        outDriver.DeleteDataSource(output_path)

    # create the spatial reference, WGS84
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    # Create the output shapefile
    outDataSource = outDriver.CreateDataSource(output_path)
    outLayer = outDataSource.CreateLayer(os.path.splitext(output_path)[0], srs, geom_type=ogr.wkbPolygon)

    # Add an ID field
    idField = ogr.FieldDefn("id", ogr.OFTInteger)
    outLayer.CreateField(idField)

    # Create the feature and set values
    featureDefn = outLayer.GetLayerDefn()
    feature = ogr.Feature(featureDefn)
    feature.SetGeometry(poly)
    feature.SetField("id", 1)
    outLayer.CreateFeature(feature)
    feature = None

    # Save and close DataSource
    inDataSource = None
    outDataSource = None

def align_list_of_datasets_to_match(input_paths, match_path, resampling_method_or_methods_list, output_paths=None, target_pixel_size=None, bounding_box_mode='match', compress=False):

    if not os.path.exists(match_path):
        raise FileNotFoundError('match_path ' + str(match_path) + ' given to align_list_of_datasets_to_match did not exist. FAIL!')

    if isinstance(resampling_method_or_methods_list, list):
        assert len(input_paths) == len(resampling_method_or_methods_list)
    elif isinstance(resampling_method_or_methods_list, str):
        resampling_method_or_methods_list = [resampling_method_or_methods_list] * len(input_paths)
    else:
        raise NameError('Failed to interpret resampling_method_or_methods_list type.')

    if output_paths is None:
        output_paths = [hb.suri(i, 'aligned') for i in input_paths]

    if target_pixel_size is None:
        target_pixel_size = hb.get_cell_size_from_uri(match_path)
    if type(target_pixel_size) not in [list, tuple]:
        target_pixel_size = [target_pixel_size, -target_pixel_size]

    if bounding_box_mode == 'match':
        # bounding_box_mode = hb.get_bounding_box(match_path)
        bounding_box_mode = hb.get_raster_info(match_path)['bounding_box']
    elif bounding_box_mode == 'global':
        bounding_box_mode = hb.common_bounding_boxes_in_degrees
    gtiff_creation_options = hb.DEFAULT_GTIFF_CREATION_OPTIONS
    if compress:
        gtiff_creation_options.append('COMPRESS=lzw')

    hb.align_and_resize_raster_stack(input_paths, output_paths, resampling_method_or_methods_list,
                                     target_pixel_size=target_pixel_size, bounding_box_mode=bounding_box_mode, gtiff_creation_options=gtiff_creation_options)


def align_dataset_to_match(input_path, match_path, output_path, mode='dataset', resample_method='bilinear', align_to_match=True,
                           aoi_uri=None, output_data_type=None, force_to_match=False, all_touched=False, verbose=False):

    if verbose:
        print ('Running align_dataset_to_match with inputs', input_path, match_path, output_path, mode, resample_method, align_to_match, aoi_uri, output_data_type, force_to_match, all_touched, verbose,)

    if mode not in ["union", "intersection", "dataset"]:
        raise Exception("Unknown mode %s" % (str(mode)))

    # get the intersecting or unioned bounding box
    if mode == "dataset":
        bounding_box = hb.get_bounding_box(match_path)
    else:
        bounding_box = reduce(
            functools.partial(hb.merge_bounding_boxes, mode=mode),
            [hb.get_bounding_box(dataset_uri) for dataset_uri in [input_path, match_path]])

    if aoi_uri != None:
        bounding_box = hb.merge_bounding_boxes(
            bounding_box, hb.get_datasource_bounding_box(aoi_uri), "intersection")

    if (bounding_box[0] >= bounding_box[2] or
        bounding_box[1] <= bounding_box[3]) and mode == "intersection":
        raise Exception("The datasets' intersection is empty "
                        "(i.e., not all the datasets touch each other).")

    if align_to_match:
        # bounding box needs alignment
        align_bounding_box = hb.get_bounding_box(match_path)
        align_pixel_size = hb.get_cell_size_from_uri(match_path)

        for index in [0, 1]:
            n_pixels = int(
                (bounding_box[index] - align_bounding_box[index]) /
                float(align_pixel_size))
            bounding_box[index] = \
                n_pixels * align_pixel_size + align_bounding_box[index]

    out_pixel_size = hb.get_cell_size_from_uri(match_path)

    input_projection = hb.get_dataset_projection_wkt_uri(input_path)
    match_projection = hb.get_dataset_projection_wkt_uri(match_path)

    if input_projection != match_projection:
        if verbose:
            print ('Input projection not same as match projection. Reprojecting.')
        temp_path = hb.temp('.tif', remove_at_exit=True)
        if force_to_match:
            # Sometimes when working with sphrical data, there is no projection set but it is  implied that it is WGS84. This is one such  case.
            # Rather than reproject (which would have a no-overlapping-data error, just redefineit as wgs84.
            output_ndv = hb.default_no_data_values_by_gdal_number[output_data_type]
            hb.force_geotiff_to_match_projection_ndv_and_datatype(input_path, match_path, temp_path, output_data_type, output_ndv)
        else:
            # If both of the datasets are properly projected, can just use reproject.
            hb.reproject_dataset_to_match(input_path, match_path, temp_path, resampling_method=resample_method)
        input_path = temp_path
    if verbose:
        print ('Running resize_and_resample_dataset_uri of ' + str(input_path) + ' to ' + str(output_path))

    hb.resize_and_resample_dataset_uri(input_path, bounding_box, out_pixel_size, output_path, resample_method, output_data_type)

    # If there's an AOI, mask it out
    if aoi_uri != None:
        if verbose:
            print ('Masking out AOI at ' + aoi_uri)
        first_dataset = gdal.Open(output_path)
        n_rows = first_dataset.RasterYSize
        n_cols = first_dataset.RasterXSize
        gdal.Dataset.__swig_destroy__(first_dataset)
        first_dataset = None

        mask_uri = hb.temp('.tif', remove_at_exit=True)
        hb.new_raster_from_base_uri(output_path, mask_uri, 'GTiff', 255,
                                    gdal.GDT_Byte, fill_value=0)

        rasterize_layer_args = {
            'options': [],
        }
        if all_touched:
            rasterize_layer_args['options'].append('ALL_TOUCHED=TRUE')

        mask_dataset = gdal.Open(mask_uri, gdal.GA_Update)
        mask_band = mask_dataset.GetRasterBand(1)
        aoi_datasource = ogr.Open(aoi_uri)
        aoi_layer = aoi_datasource.GetLayer()
        gdal.RasterizeLayer(mask_dataset, [1], aoi_layer, burn_values=[1], **rasterize_layer_args)
        mask_row = numpy.zeros((1, n_cols), dtype=numpy.int8)

        output_dataset = gdal.Open(output_path, gdal.GA_Update)
        output_band = output_dataset.GetRasterBand(1)
        nodata_out = hb.get_nodata_from_uri(output_path)

        for row_index in range(n_rows):
            mask_row = (mask_band.ReadAsArray(0, row_index, n_cols, 1) == 0)
            dataset_row = output_band.ReadAsArray(0, row_index, n_cols, 1)
            output_band.WriteArray(
                np.where(mask_row, nodata_out, dataset_row),
                xoff=0, yoff=row_index)

        # Remove the mask aoi if necessary
        mask_band = None
        gdal.Dataset.__swig_destroy__(mask_dataset)
        mask_dataset = None
        # Make sure the dataset is closed and cleaned up
        os.remove(mask_uri)

        aoi_layer = None
        ogr.DataSource.__swig_destroy__(aoi_datasource)
        aoi_datasource = None

        # Clean up datasets
        output_band = None
        output_dataset.FlushCache()
        gdal.Dataset.__swig_destroy__(output_dataset)
        output_dataset = None

def reproject_dataset_to_match(input_path, match_path, output_path, resampling_method):
    # A dictionary to map the resampling method input string to the gdal type
    resample_dict = {
        "nearest": gdal.GRA_NearestNeighbour,
        "nearest_neighbor": gdal.GRA_NearestNeighbour,
        "near": gdal.GRA_NearestNeighbour,
        "bilinear": gdal.GRA_Bilinear,
        "cubic": gdal.GRA_Cubic,
        "cubic_spline": gdal.GRA_CubicSpline,
        "lanczos": gdal.GRA_Lanczos,
        "average": gdal.GRA_Average,
    }

    # Get the nodata value and datatype from the original dataset
    output_type = hb.get_datatype_from_uri(match_path)
    out_nodata = hb.get_nodata_from_uri(match_path)
    pixel_spacing = hb.get_cell_size_from_uri(match_path)

    original_dataset = gdal.Open(input_path)
    original_wkt = original_dataset.GetProjection()

    match_dataset = gdal.Open(match_path)
    output_wkt = match_dataset.GetProjection()

    # Create a virtual raster that is projected based on the output WKT. This
    # vrt does not save to disk and is used to get the proper projected bounding
    # box and size.
    vrt = gdal.AutoCreateWarpedVRT(
        original_dataset, None, output_wkt, gdal.GRA_Bilinear)

    geo_t = vrt.GetGeoTransform()
    x_size = vrt.RasterXSize # Raster xsize
    y_size = vrt.RasterYSize # Raster ysize

    # Calculate the extents of the projected dataset. These values will be used
    # to properly set the resampled size for the output dataset
    (ulx, uly) = (geo_t[0], geo_t[3])
    (lrx, lry) = (geo_t[0] + geo_t[1] * x_size, geo_t[3] + geo_t[5] * y_size)

    gdal_driver = gdal.GetDriverByName('GTiff')

    # Create the output dataset to receive the projected output, with the proper
    # resampled arrangement.
    output_dataset = gdal_driver.Create(
        output_path, int((lrx - ulx)/pixel_spacing),
        int((uly - lry)/pixel_spacing), 1, output_type,
        options=['BIGTIFF=IF_SAFER'])

    # Set the nodata value for the output dataset
    output_dataset.GetRasterBand(1).SetNoDataValue(float(out_nodata))

    # Calculate the new geotransform
    output_geo = (ulx, pixel_spacing, geo_t[2], uly, geo_t[4], -pixel_spacing)

    # Set the geotransform
    output_dataset.SetGeoTransform(output_geo)
    output_dataset.SetProjection(output_wkt)


    def reproject_callback(df_complete, psz_message, p_progress_arg):
        """The argument names come from the GDAL API for callbacks."""
        try:
            current_time = time.time()
            if ((current_time - reproject_callback.last_time) > 3.0 or
                    (df_complete == 1.0 and reproject_callback.total_time >= 3.0)):
                print ("ReprojectImage " + str(df_complete * 100) + " percent complete")
                reproject_callback.last_time = current_time
                reproject_callback.total_time += current_time
        except AttributeError:
            reproject_callback.last_time = time.time()
            reproject_callback.total_time = 0.0

    # # Perform the projection/resampling
    # gdal.ReprojectImage(
    #     original_dataset, output_dataset, original_wkt, output_wkt,
    #     resample_dict[resampling_method])

    # Perform the projection/resampling
    gdal.ReprojectImage(
        original_dataset, output_dataset, original_wkt, output_wkt,
        resample_dict[resampling_method], 0, 0,
        reproject_callback, [output_path])

    output_dataset.FlushCache()

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(output_dataset)
    output_dataset = None

    hb.calculate_raster_stats_uri(output_path)


def normalize_array(array, low=0, high=1, log_transform=True, **kwargs):

    if log_transform:
        min = np.min(array)
        max = np.max(array)
        to_add = float(min * -1.0 + 1.0)
        array = array + to_add

        array = np.log(array)

    min = np.min(array)
    max = np.max(array)

    normalizer = (high - low) / (max - min)

    output_array = (array - min) *  normalizer

    return output_array

def cast_to_np64(a):
    if isinstance(a, np.ndarray):
        if a.dtype in [np.bool, np.int, np.int8, np.int16, np.int32, np.int64, np.uint, np.uint8, np.uint16, np.uint32, np.uint64]:
            return a.astype(np.int64)
        else:
            return a.astype(np.float64)
    else:
        if isinstance(a, int):
            return np.int64(a)
        else:
            return np.float64(float(a))

def reclassify(input_array, rules):

    casted_array = cast_to_np64(input_array)

    if casted_array.dtype == 'float64':
        if isinstance(list(rules.values())[0], float):
            reclassified_array = hb.memory_view_reclassify_float_array_by_dict_to_floats(casted_array, rules)
        else:
            reclassified_array = hb.memory_view_reclassify_float_array_by_dict_to_ints(casted_array, rules)
    else:
        if isinstance(list(rules.values())[0], float):
            reclassified_array = hb.memory_view_reclassify_int_array_by_dict_to_floats(casted_array, rules)
        else:
            reclassified_array = hb.memory_view_reclassify_int_array_by_dict_to_ints(casted_array, rules)

    return np.array(reclassified_array)



def create_buffered_polygon(input_uri, output_uri, buffer_cell_width):

    driver = ogr.GetDriverByName("ESRI Shapefile")
    input_ds = driver.Open(input_uri, 0)
    input_layer = input_ds.GetLayer()
    input_srs = input_layer.GetSpatialRef()

    # Assume output will have same srs as input
    output_srs = input_srs

    # Create the output Layer
    output_ds = driver.CreateDataSource(output_uri)
    output_layer = output_ds.CreateLayer("buffered", output_srs, geom_type=ogr.wkbMultiPolygon)

    # Add input Layer Fields to the output Layer
    input_layer_def = output_layer.GetLayerDefn()
    for i in range(0, input_layer_def.GetFieldCount()):
        field_def = input_layer_def.GetFieldDefn(i)
        output_layer.CreateField(field_def)

    # Get the output Layer's Feature Definition
    output_layer_def = output_layer.GetLayerDefn()

    # Add features to the ouput Layer
    for i in range(0, input_layer.GetFeatureCount()):
        # Get the input Feature
        input_feature = input_layer.GetFeature(i)
        # Create output Feature
        output_feature = ogr.Feature(output_layer_def)
        # Add field values from input Layer
        for i in range(0, output_layer_def.GetFieldCount()):
            output_feature.SetField(output_layer_def.GetFieldDefn(i).GetNameRef(), input_feature.GetField(i))
        # Set geometry as centroid
        geom = input_feature.GetGeometryRef()
        centroid = geom.Centroid()
        buffered_geom = geom.Buffer(buffer_cell_width)
        output_feature.SetGeometry(buffered_geom)
        # Add new feature to output Layer
        output_layer.CreateFeature(output_feature)

    # Close datasources
    input_ds.Destroy()
    output_ds.Destroy()

def get_cell_size_from_uri(dataset_uri):
    """Get the cell size of a dataset in units of meters.

    Raises an exception if the raster is not square since this'll break most of
    the pygeoprocessing algorithms.

    Args:
        dataset_uri (string): uri to a gdal dataset

    Returns:
        size_meters: cell size of the dataset in meters
    """

    srs = osr.SpatialReference()
    dataset = gdal.Open(dataset_uri)
    if dataset is None:
        raise IOError(
            'File not found or not valid dataset type at: %s' % dataset_uri)
    srs.SetProjection(dataset.GetProjection())
    linear_units = srs.GetLinearUnits()
    geotransform = dataset.GetGeoTransform()

    # take absolute value since sometimes negative widths/heights
    try:
        numpy.testing.assert_approx_equal(
            abs(geotransform[1]), abs(geotransform[5]))
        size_meters = abs(geotransform[1]) * linear_units
    except AssertionError as e:
        L.warn(e)
        size_meters = (
                              abs(geotransform[1]) + abs(geotransform[5])) / 2.0 * linear_units

    # Close and clean up dataset
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return size_meters

def get_datatype_from_uri(dataset_uri):
    """
    Returns the datatype for the first band from a gdal dataset

    Args:
        dataset_uri (string): a uri to a gdal dataset

    Returns:
        datatype (?): datatype for dataset band 1"""

    dataset = gdal.Open(dataset_uri)
    band = dataset.GetRasterBand(1)
    datatype = band.DataType

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return datatype


def get_row_col_from_uri(dataset_uri):
    """
    Returns a tuple of number of rows and columns of that dataset uri.

    Args:
        dataset_uri (string): a uri to a gdal dataset

    Returns:
        tuple (tuple): 2-tuple (n_row, n_col) from dataset_uri"""

    dataset = gdal.Open(dataset_uri)
    n_rows = dataset.RasterYSize
    n_cols = dataset.RasterXSize

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return (n_rows, n_cols)

def get_statistics_from_uri(dataset_uri):
    """
    Retrieves the min, max, mean, stdev from a GDAL Dataset

    Args:
        dataset_uri (string): a uri to a gdal dataset

    Returns:
        statistics (?): min, max, mean, stddev

    """

    dataset = gdal.Open(dataset_uri)
    band = dataset.GetRasterBand(1)
    statistics = band.GetStatistics(0, 1)

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return statistics

def pixel_size_based_on_coordinate_transform_uri(dataset_uri, *args, **kwargs):
    """
    A wrapper for pixel_size_based_on_coordinate_transform that takes a dataset
    uri as an input and opens it before sending it along

    Args:
        dataset_uri (string): a URI to a gdal dataset

        All other parameters pass along

    Returns:
        result (tuple): a tuple containing (pixel width in meters, pixel height
            in meters)

    """
    dataset = gdal.Open(dataset_uri)
    result = pixel_size_based_on_coordinate_transform(dataset, *args, **kwargs)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return result

def pixel_size_based_on_coordinate_transform(dataset, coord_trans, point):
    """
    Calculates the pixel width and height in meters given a coordinate
    transform and reference point on the dataset that's close to the
    transform's projected coordinate sytem.  This is only necessary
    if dataset is not already in a meter coordinate system, for example
    dataset may be in lat/long (WGS84).

    Args:
        dataset (?): a projected GDAL dataset in the form of lat/long decimal
            degrees
        coord_trans (?): an OSR coordinate transformation from dataset
            coordinate system to meters
        point (?): a reference point close to the coordinate transform
            coordinate system.  must be in the same coordinate system as
            dataset.

    Returns:
        pixel_diff (tuple): a 2-tuple containing (pixel width in meters, pixel
            height in meters)
    """
    #Get the first points (x, y) from geoTransform
    geo_tran = dataset.GetGeoTransform()
    pixel_size_x = geo_tran[1]
    pixel_size_y = geo_tran[5]
    top_left_x = point[0]
    top_left_y = point[1]
    #Create the second point by adding the pixel width/height
    new_x = top_left_x + pixel_size_x
    new_y = top_left_y + pixel_size_y
    #Transform two points into meters
    point_1 = coord_trans.TransformPoint(top_left_x, top_left_y)
    point_2 = coord_trans.TransformPoint(new_x, new_y)
    #Calculate the x/y difference between two points
    #taking the absolue value because the direction doesn't matter for pixel
    #size in the case of most coordinate systems where y increases up and x
    #increases to the right (right handed coordinate system).
    pixel_diff_x = abs(point_2[0] - point_1[0])
    pixel_diff_y = abs(point_2[1] - point_1[1])
    return (pixel_diff_x, pixel_diff_y)

def new_raster(
        cols, rows, projection, geotransform, format_, nodata, datatype,
        bands, outputURI):

    """
    Create a new raster with the given properties.

    Args:
        cols (int): number of pixel columns
        rows (int): number of pixel rows
        projection (?): the datum
        geotransform (?): the coordinate system
        format_ (string): a string representing the GDAL file format_ of the
            output raster.  See http://gdal.org/formats_list.html for a list
            of available formats.  This parameter expects the format_ code, such
            as 'GTiff' or 'MEM'
        nodata (?): a value that will be set as the nodata value for the
            output raster.  Should be the same type as 'datatype'
        datatype (?): the pixel datatype of the output raster, for example
            gdal.GDT_Float32.  See the following header file for supported
            pixel types:
            http://www.gdal.org/gdal_8h.html#22e22ce0a55036a96f652765793fb7a4
        bands (int): the number of bands in the raster
        outputURI (string): the file location for the outputed raster.  If
            format_ is 'MEM' this can be an empty string

    Returns:
        dataset (?): a new GDAL raster with the parameters as described above

    """

    driver = gdal.GetDriverByName(format_)
    new_raster = driver.Create(
        outputURI.encode('utf-8'), cols, rows, bands, datatype,
        options=['BIGTIFF=IF_SAFER'])
    new_raster.SetProjection(projection)
    new_raster.SetGeoTransform(geotransform)
    for i in range(bands):
        new_raster.GetRasterBand(i + 1).SetNoDataValue(nodata)
        new_raster.GetRasterBand(i + 1).Fill(nodata)

    return new_raster

def calculate_intersection_rectangle(dataset_list, aoi=None):
    """
    Return a bounding box of the intersections of all the rasters in the
    list.

    Args:
        dataset_list (list): a list of GDAL datasets in the same projection and
            coordinate system

    Keyword Args:
        aoi (?): an OGR polygon datasource which may optionally also restrict
            the extents of the intersection rectangle based on its own
            extents.

    Returns:
        bounding_box (list): a 4 element list that bounds the intersection of
            all the rasters in dataset_list.  [left, top, right, bottom]

    Raises:
        SpatialExtentOverlapException: in cases where the dataset list and aoi
            don't overlap.

    """

    def valid_bounding_box(bb):
        """
        Check to make sure bounding box doesn't collapse on itself

        Args:
            bb (list): a bounding box of the form [left, top, right, bottom]

        Returns:
            is_valid (boolean): True if bb is valid, false otherwise"""

        return bb[0] <= bb[2] and bb[3] <= bb[1]

    #Define the initial bounding box
    gt = dataset_list[0].GetGeoTransform()
    #order is left, top, right, bottom of rasterbounds
    bounding_box = [
        gt[0], gt[3], gt[0] + gt[1] * dataset_list[0].RasterXSize,
                      gt[3] + gt[5] * dataset_list[0].RasterYSize]

    dataset_files = []
    for dataset in dataset_list:
        dataset_files.append(dataset.GetDescription())
        #intersect the current bounding box with the one just read
        gt = dataset.GetGeoTransform()
        rec = [
            gt[0], gt[3], gt[0] + gt[1] * dataset.RasterXSize,
                          gt[3] + gt[5] * dataset.RasterYSize]
        #This intersects rec with the current bounding box
        bounding_box = [
            max(rec[0], bounding_box[0]),
            min(rec[1], bounding_box[1]),
            min(rec[2], bounding_box[2]),
            max(rec[3], bounding_box[3])]

        #Left can't be greater than right or bottom greater than top
        if not valid_bounding_box(bounding_box):
            raise SpatialExtentOverlapException(
                "These rasters %s don't overlap with this one %s" %
                (str(dataset_files[0:-1]), dataset_files[-1]))

    if aoi != None:
        aoi_layer = aoi.GetLayer(0)
        aoi_extent = aoi_layer.GetExtent()
        bounding_box = [
            max(aoi_extent[0], bounding_box[0]),
            min(aoi_extent[3], bounding_box[1]),
            min(aoi_extent[1], bounding_box[2]),
            max(aoi_extent[2], bounding_box[3])]
        if not valid_bounding_box(bounding_box):
            raise SpatialExtentOverlapException(
                "The aoi layer %s doesn't overlap with %s" %
                (aoi, str(dataset_files)))

    return bounding_box


def create_raster_from_vector_extents_uri(
        shapefile_uri, pixel_size, gdal_format, nodata_out_value, output_uri):
    """
    A wrapper for create_raster_from_vector_extents

    Args:
        shapefile_uri (string): uri to an OGR datasource to use as the extents
            of the raster
        pixel_size (?): size of output pixels in the projected units of
            shapefile_uri
        gdal_format (?): the raster pixel format, something like
            gdal.GDT_Float32
        nodata_out_value (?): the output nodata value
        output_uri (string): the URI to write the gdal dataset

    Returns:


    """

    datasource = ogr.Open(shapefile_uri)
    create_raster_from_vector_extents(
        pixel_size, pixel_size, gdal_format, nodata_out_value, output_uri,
        datasource)


def OLD_create_raster_from_vector_extents(
        xRes, yRes, format_, nodata, rasterFile, shp):
    """
    Create a blank raster based on a vector file extent.  This code is
    adapted from http://trac.osgeo.org/gdal/wiki/FAQRaster#HowcanIcreateablankrasterbasedonavectorfilesextentsforusewithgdal_rasterizeGDAL1.8.0

    Args:
        xRes (?): the x size of a pixel in the output dataset must be a
            positive value
        yRes (?): the y size of a pixel in the output dataset must be a
            positive value
        format_ (?): gdal GDT pixel type
        nodata (?): the output nodata value
        rasterFile (string): URI to file location for raster
        shp (?): vector shapefile to base extent of output raster on

    Returns:
        raster (?): blank raster whose bounds fit within `shp`s bounding box
            and features are equivalent to the passed in data

    """

    #Determine the width and height of the tiff in pixels based on the
    #maximum size of the combined envelope of all the features
    shp_extent = None
    for layer_index in range(shp.GetLayerCount()):
        shp_layer = shp.GetLayer(layer_index)
        for feature_index in range(shp_layer.GetFeatureCount()):
            try:
                feature = shp_layer.GetFeature(feature_index)
                geometry = feature.GetGeometryRef()

                #feature_extent = [xmin, xmax, ymin, ymax]
                feature_extent = geometry.GetEnvelope()
                #This is an array based way of mapping the right function
                #to the right index.
                functions = [min, max, min, max]
                for i in range(len(functions)):
                    try:
                        shp_extent[i] = functions[i](
                            shp_extent[i], feature_extent[i])
                    except TypeError:
                        #need to cast to list because returned as a tuple
                        #and we can't assign to a tuple's index, also need to
                        #define this as the initial state
                        shp_extent = list(feature_extent)
            except AttributeError as e:
                #For some valid OGR objects the geometry can be undefined since
                #it's valid to have a NULL entry in the attribute table
                #this is expressed as a None value in the geometry reference
                #this feature won't contribute
                L.warning(e)

    #shp_extent = [xmin, xmax, ymin, ymax]
    tiff_width = int(numpy.ceil(abs(shp_extent[1] - shp_extent[0]) / xRes))
    tiff_height = int(numpy.ceil(abs(shp_extent[3] - shp_extent[2]) / yRes))

    if rasterFile != None:
        driver = gdal.GetDriverByName('GTiff')
    else:
        rasterFile = ''
        driver = gdal.GetDriverByName('MEM')
    #1 means only create 1 band
    raster = driver.Create(
        rasterFile, tiff_width, tiff_height, 1, format_,
        options=['BIGTIFF=IF_SAFER'])
    raster.GetRasterBand(1).SetNoDataValue(nodata)

    #Set the transform based on the upper left corner and given pixel
    #dimensions
    raster_transform = [shp_extent[0], xRes, 0.0, shp_extent[3], 0.0, -yRes]
    raster.SetGeoTransform(raster_transform)

    #Use the same projection on the raster as the shapefile
    srs = osr.SpatialReference()
    srs.ImportFromWkt(shp.GetLayer(0).GetSpatialRef().__str__())
    raster.SetProjection(srs.ExportToWkt())

    #Initialize everything to nodata
    raster.GetRasterBand(1).Fill(nodata)
    raster.GetRasterBand(1).FlushCache()

    return raster

def vectorize_points(
        shapefile, datasource_field, dataset, randomize_points=False,
        mask_convex_hull=False, interpolation='nearest'):
    """
    Takes a shapefile of points and a field defined in that shapefile
    and interpolates the values in the points onto the given raster

    Args:
        shapefile (?): ogr datasource of points
        datasource_field (?): a field in shapefile
        dataset (?): a gdal dataset must be in the same projection as shapefile

    Keyword Args:
        randomize_points (boolean): (description)
        mask_convex_hull (boolean): (description)
        interpolation (string): the interpolation method to use for
            scipy.interpolate.griddata(). Default is 'nearest'

    Returns:
       nothing

    """

    #Define the initial bounding box
    gt = dataset.GetGeoTransform()
    #order is left, top, right, bottom of rasterbounds
    bounding_box = [gt[0], gt[3], gt[0] + gt[1] * dataset.RasterXSize,
                    gt[3] + gt[5] * dataset.RasterYSize]

    def in_bounds(point):
        return point[0] <= bounding_box[2] and point[0] >= bounding_box[0] \
               and point[1] <= bounding_box[1] and point[1] >= bounding_box[3]

    layer = shapefile.GetLayer(0)
    point_list = []
    value_list = []

    #Calculate a small amount to perturb points by so that we don't
    #get a linear Delauney triangle, the 1e-6 is larger than eps for
    #floating point, but large enough not to cause errors in interpolation.
    delta_difference = 1e-6 * min(abs(gt[1]), abs(gt[5]))
    if randomize_points:
        random_array = numpy.random.randn(layer.GetFeatureCount(), 2)
        random_offsets = random_array*delta_difference
    else:
        random_offsets = numpy.zeros((layer.GetFeatureCount(), 2))

    for feature_id in range(layer.GetFeatureCount()):
        feature = layer.GetFeature(feature_id)
        geometry = feature.GetGeometryRef()
        #Here the point geometry is in the form x, y (col, row)
        point = geometry.GetPoint()
        if in_bounds(point):
            value = feature.GetField(datasource_field)
            #Add in the numpy notation which is row, col
            point_list.append([point[1]+random_offsets[feature_id, 1],
                               point[0]+random_offsets[feature_id, 0]])
            value_list.append(value)

    point_array = numpy.array(point_list)
    value_array = numpy.array(value_list)

    band = dataset.GetRasterBand(1)

    #Create grid points for interpolation outputs later
    #top-bottom:y_stepsize, left-right:x_stepsize

    #Make as an integer grid then divide subtract by bounding box parts
    #so we don't get a roundoff error and get off by one pixel one way or
    #the other
    grid_y, grid_x = numpy.mgrid[0:band.YSize, 0:band.XSize]
    grid_y = grid_y * gt[5] + bounding_box[1]
    grid_x = grid_x * gt[1] + bounding_box[0]

    nodata = band.GetNoDataValue()

    raster_out_array = scipy.interpolate.griddata(
        point_array, value_array, (grid_y, grid_x), interpolation, nodata)
    band.WriteArray(raster_out_array, 0, 0)

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None


def aggregate_raster_values_uri(
        raster_uri, shapefile_uri, shapefile_field=None, ignore_nodata=True,
        threshold_amount_lookup=None, ignore_value_list=[], process_pool=None,
        all_touched=False):

    """
    Collect all the raster values that lie in shapefile depending on the
    value of operation

    Args:
        raster_uri (string): a uri to a GDAL dataset
        shapefile_uri (string): a uri to a OGR datasource that should overlap
            raster; raises an exception if not.

    Keyword Args:
        shapefile_field (string): a string indicating which key in shapefile to
            associate the output dictionary values with whose values are
            associated with ints; if None dictionary returns a value over
            the entire shapefile region that intersects the raster.
        ignore_nodata (?): if operation == 'mean' then it does not
            account for nodata pixels when determining the pixel_mean,
            otherwise all pixels in the AOI are used for calculation of the
            mean.  This does not affect hectare_mean which is calculated from
            the geometrical area of the feature.
        threshold_amount_lookup (dict): a dictionary indexing the
            shapefile_field's to threshold amounts to subtract from the
            aggregate value.  The result will be clamped to zero.
        ignore_value_list (list): a list of values to ignore when
            calculating the stats
        process_pool (?): a process pool for multiprocessing
        all_touched (boolean): if true will account for any pixel whose
            geometry passes through the pixel, not just the center point

    Returns:
        result_tuple (tuple): named tuple of the form
           ('aggregate_values', 'total pixel_mean hectare_mean n_pixels
            pixel_min pixel_max')
           Each of [sum pixel_mean hectare_mean] contains a dictionary that
           maps shapefile_field value to the total, pixel mean, hecatare mean,
           pixel max, and pixel min of the values under that feature.
           'n_pixels' contains the total number of valid pixels used in that
           calculation.  hectare_mean is None if raster_uri is unprojected.

    Raises:
        AttributeError
        TypeError
        OSError

    """

    raster_nodata = hb.get_nodata_from_uri(raster_uri)
    out_pixel_size = get_cell_size_from_uri(raster_uri)
    clipped_raster_uri = hb.temporary_filename(suffix='.tif', remove_at_exit=True)
    vectorize_datasets(
        [raster_uri], lambda x: x, clipped_raster_uri, gdal.GDT_Float64,
        raster_nodata, out_pixel_size, "union",
        dataset_to_align_index=0, aoi_uri=shapefile_uri,
        assert_datasets_projected=False, process_pool=process_pool,
        vectorize_op=False)
    clipped_raster = gdal.Open(clipped_raster_uri)

    #This should be a value that's not in shapefile[shapefile_field]
    mask_nodata = -1
    mask_uri = hb.temporary_filename(suffix='.tif', remove_at_exit=True)
    hb.new_raster_from_base_uri(
        clipped_raster_uri, mask_uri, 'GTiff', mask_nodata,
        gdal.GDT_Int32, fill_value=mask_nodata)

    mask_dataset = gdal.Open(mask_uri, gdal.GA_Update)
    shapefile = ogr.Open(shapefile_uri)
    shapefile_layer = shapefile.GetLayer()
    rasterize_layer_args = {
        'options': [],
    }

    if all_touched:
        rasterize_layer_args['options'].append('ALL_TOUCHED=TRUE')

    if shapefile_field is not None:
        #Make sure that the layer name refers to an integer
        layer_d = shapefile_layer.GetLayerDefn()
        fd = layer_d.GetFieldDefn(layer_d.GetFieldIndex(shapefile_field))
        if fd == -1 or fd is None:  # -1 returned when field does not exist.
            # Raise exception if user provided a field that's not in vector
            raise AttributeError(
                'Vector %s must have a field named %s' %
                (shapefile_uri, shapefile_field))
        if fd.GetTypeName() != 'Integer':
            raise TypeError(
                'Can only aggreggate by integer based fields, requested '
                'field is of type  %s' % fd.GetTypeName())
        #Adding the rasterize by attribute option
        rasterize_layer_args['options'].append(
            'ATTRIBUTE=%s' % shapefile_field)
    else:
        #9999 is a classic unknown value
        global_id_value = 9999
        rasterize_layer_args['burn_values'] = [global_id_value]

    #loop over the subset of feature layers and rasterize/aggregate each one
    aggregate_dict_values = {}
    aggregate_dict_counts = {}
    AggregatedValues = collections.namedtuple(
        'AggregatedValues',
        'total pixel_mean hectare_mean n_pixels pixel_min pixel_max')
    result_tuple = AggregatedValues(
        total={},
        pixel_mean={},
        hectare_mean={},
        n_pixels={},
        pixel_min={},
        pixel_max={})

    #make a shapefile that non-overlapping layers can be added to
    driver = ogr.GetDriverByName('ESRI Shapefile')
    layer_dir = temporary_folder()
    subset_layer_datasouce = driver.CreateDataSource(
        os.path.join(layer_dir, 'subset_layer.shp'))
    spat_ref = get_spatial_ref_uri(shapefile_uri)
    subset_layer = subset_layer_datasouce.CreateLayer(
        'subset_layer', spat_ref, ogr.wkbPolygon)
    defn = shapefile_layer.GetLayerDefn()

    #For every field, create a duplicate field and add it to the new
    #subset_layer layer
    defn.GetFieldCount()
    for fld_index in range(defn.GetFieldCount()):
        original_field = defn.GetFieldDefn(fld_index)
        output_field = ogr.FieldDefn(
            original_field.GetName(), original_field.GetType())
        subset_layer.CreateField(output_field)

    #Initialize these dictionaries to have the shapefile fields in the original
    #datasource even if we don't pick up a value later

    #This will store the sum/count with index of shapefile attribute
    if shapefile_field is not None:
        shapefile_table = extract_datasource_table_by_key(
            shapefile_uri, shapefile_field)
    else:
        shapefile_table = {global_id_value: 0.0}

    current_iteration_shapefiles = dict([
        (shapefile_id, 0.0) for shapefile_id in shapefile_table.keys()])
    aggregate_dict_values = current_iteration_shapefiles.copy()
    aggregate_dict_counts = current_iteration_shapefiles.copy()
    #Populate the means and totals with something in case the underlying raster
    #doesn't exist for those features.  we use -9999 as a recognizable nodata
    #value.
    for shapefile_id in shapefile_table:
        result_tuple.pixel_mean[shapefile_id] = -9999
        result_tuple.total[shapefile_id] = -9999
        result_tuple.hectare_mean[shapefile_id] = -9999

    pixel_min_dict = dict(
        [(shapefile_id, None) for shapefile_id in shapefile_table.keys()])
    pixel_max_dict = pixel_min_dict.copy()

    #Loop over each polygon and aggregate
    minimal_polygon_sets = calculate_disjoint_polygon_set(
        shapefile_uri)

    clipped_band = clipped_raster.GetRasterBand(1)
    n_rows = clipped_band.YSize
    n_cols = clipped_band.XSize
    block_col_size, block_row_size = clipped_band.GetBlockSize()

    for polygon_set in minimal_polygon_sets:
        #add polygons to subset_layer
        for poly_fid in polygon_set:
            poly_feat = shapefile_layer.GetFeature(poly_fid)
            subset_layer.CreateFeature(poly_feat)
        subset_layer_datasouce.SyncToDisk()

        #nodata out the mask
        mask_band = mask_dataset.GetRasterBand(1)
        mask_band.Fill(mask_nodata)
        mask_band = None

        gdal.RasterizeLayer(
            mask_dataset, [1], subset_layer, **rasterize_layer_args)

        #get feature areas
        num_features = subset_layer.GetFeatureCount()
        feature_areas = collections.defaultdict(int)
        for feature in subset_layer:
            #feature = subset_layer.GetFeature(index)
            geom = feature.GetGeometryRef()
            if shapefile_field is not None:
                feature_id = feature.GetField(shapefile_field)
                feature_areas[feature_id] = geom.GetArea()
            else:
                feature_areas[global_id_value] += geom.GetArea()
        subset_layer.ResetReading()
        geom = None

        #Need a complicated step to see what the FIDs are in the subset_layer
        #then need to loop through and delete them
        fid_to_delete = set()
        for feature in subset_layer:
            fid_to_delete.add(feature.GetFID())
        subset_layer.ResetReading()
        for fid in fid_to_delete:
            subset_layer.DeleteFeature(fid)
        subset_layer_datasouce.SyncToDisk()

        mask_dataset.FlushCache()
        mask_band = mask_dataset.GetRasterBand(1)
        current_iteration_attribute_ids = set()

        for global_block_row in range(int(numpy.ceil(float(n_rows) / block_row_size))):
            for global_block_col in range(int(numpy.ceil(float(n_cols) / block_col_size))):
                global_col = global_block_col*block_col_size
                global_row = global_block_row*block_row_size
                global_col_size = min((global_block_col+1)*block_col_size, n_cols) - global_col
                global_row_size = min((global_block_row+1)*block_row_size, n_rows) - global_row
                mask_array = mask_band.ReadAsArray(
                    global_col, global_row, global_col_size, global_row_size)
                clipped_array = clipped_band.ReadAsArray(
                    global_col, global_row, global_col_size, global_row_size)

                unique_ids = numpy.unique(mask_array)
                current_iteration_attribute_ids = (
                    current_iteration_attribute_ids.union(unique_ids))
                for attribute_id in unique_ids:
                    #ignore masked values
                    if attribute_id == mask_nodata:
                        continue

                    #Only consider values which lie in the polygon for attribute_id
                    masked_values = clipped_array[
                        (mask_array == attribute_id) &
                        (~numpy.isnan(clipped_array))]
                    #Remove the nodata and ignore values for later processing
                    masked_values_nodata_removed = (
                        masked_values[~numpy.in1d(
                            masked_values, [raster_nodata] + ignore_value_list).
                            reshape(masked_values.shape)])

                    #Find the min and max which might not yet be calculated
                    if masked_values_nodata_removed.size > 0:
                        if pixel_min_dict[attribute_id] is None:
                            pixel_min_dict[attribute_id] = numpy.min(
                                masked_values_nodata_removed)
                            pixel_max_dict[attribute_id] = numpy.max(
                                masked_values_nodata_removed)
                        else:
                            pixel_min_dict[attribute_id] = min(
                                pixel_min_dict[attribute_id],
                                numpy.min(masked_values_nodata_removed))
                            pixel_max_dict[attribute_id] = max(
                                pixel_max_dict[attribute_id],
                                numpy.max(masked_values_nodata_removed))

                    if ignore_nodata:
                        #Only consider values which are not nodata values
                        aggregate_dict_counts[attribute_id] += (
                            masked_values_nodata_removed.size)
                    else:
                        aggregate_dict_counts[attribute_id] += masked_values.size

                    aggregate_dict_values[attribute_id] += numpy.sum(
                        masked_values_nodata_removed)

        #Initialize the dictionary to have an n_pixels field that contains the
        #counts of all the pixels used in the calculation.
        result_tuple.n_pixels.update(aggregate_dict_counts.copy())
        result_tuple.pixel_min.update(pixel_min_dict.copy())
        result_tuple.pixel_max.update(pixel_max_dict.copy())
        #Don't want to calculate stats for the nodata
        current_iteration_attribute_ids.discard(mask_nodata)
        for attribute_id in current_iteration_attribute_ids:
            if threshold_amount_lookup != None:
                adjusted_amount = max(
                    aggregate_dict_values[attribute_id] -
                    threshold_amount_lookup[attribute_id], 0.0)
            else:
                adjusted_amount = aggregate_dict_values[attribute_id]

            result_tuple.total[attribute_id] = adjusted_amount

            if aggregate_dict_counts[attribute_id] != 0.0:
                n_pixels = aggregate_dict_counts[attribute_id]
                result_tuple.pixel_mean[attribute_id] = (
                        adjusted_amount / n_pixels)

                #To get the total area multiply n pixels by their area then
                #divide by 10000 to get Ha.  Notice that's in the denominator
                #so the * 10000 goes on the top
                if feature_areas[attribute_id] == 0:
                    L.warning('feature_areas[%d]=0' % (attribute_id))
                    result_tuple.hectare_mean[attribute_id] = 0.0
                else:
                    result_tuple.hectare_mean[attribute_id] = (
                            adjusted_amount / feature_areas[attribute_id] * 10000)
            else:
                result_tuple.pixel_mean[attribute_id] = 0.0
                result_tuple.hectare_mean[attribute_id] = 0.0

        try:
            assert_datasets_in_same_projection([raster_uri])
        except DatasetUnprojected:
            #doesn't make sense to calculate the hectare mean
            L.warning(
                'raster %s is not projected setting hectare_mean to {}'
                % raster_uri)
            result_tuple.hectare_mean.clear()

    #Make sure the dataset is closed and cleaned up
    mask_band = None
    gdal.Dataset.__swig_destroy__(mask_dataset)
    mask_dataset = None

    #Make sure the dataset is closed and cleaned up
    clipped_band = None
    gdal.Dataset.__swig_destroy__(clipped_raster)
    clipped_raster = None

    for filename in [mask_uri, clipped_raster_uri]:
        try:
            os.remove(filename)
        except OSError:
            L.warning("couldn't remove file %s" % filename)

    subset_layer = None
    ogr.DataSource.__swig_destroy__(subset_layer_datasouce)
    subset_layer_datasouce = None
    try:
        shutil.rmtree(layer_dir)
    except OSError:
        L.warning("couldn't remove directory %s" % layer_dir)

    return result_tuple

def extract_band_and_nodata(dataset, get_array=False):
    """
    It's often useful to get the first band and corresponding nodata value
    for a dataset.  This function does that.

    Args:
        dataset (?): a GDAL dataset

    Keyword Args:
        get_array (boolean): if True also returns the dataset as a numpy array

    Returns:
        band (?): first GDAL band in dataset
        nodata (?: nodata value for that band

    """

    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue()

    #gdal has strange behaviors with nodata and byte rasters, this packs it into the right space
    if band.DataType == gdal.GDT_Byte and nodata is not None:
        nodata = nodata % 256

    if get_array:
        array = band.ReadAsArray()
        return band, nodata, array

    #Otherwise just return the band and nodata
    return band, nodata



def calculate_value_not_in_dataset_uri(dataset_uri):
    """
    Calculate a value not contained in a dataset.  Useful for calculating
    nodata values.

    Args:
        dataset (?): a GDAL dataset

    Returns:
        value (?): number not contained in the dataset

    """
    dataset = gdal.Open(dataset_uri)
    value = calculate_value_not_in_dataset(dataset)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return value


def calculate_value_not_in_dataset(dataset):
    """
    Calculate a value not contained in a dataset.  Useful for calculating
    nodata values.

    Args:
        dataset (?): a GDAL dataset

    Returns:
        value (?): number not contained in the dataset

    """

    _, _, array = extract_band_and_nodata(dataset, get_array=True)
    return calculate_value_not_in_array(array)


def calculate_value_not_in_array(array):
    """
    This function calculates a number that is not in the given array, if
    possible.

    Args:
        array (np.array): a numpy array

    Returns:
        value (?): a number not in array that is not "close" to any value in
            array calculated in the middle of the maximum delta between any two
            consecutive numbers in the array

    """

    sorted_array = numpy.sort(numpy.unique(array.flatten()))
    #Make sure we don't have a single unique value, if we do just go + or -
    #1 at the end
    if len(sorted_array) > 1:
        array_type = type(sorted_array[0])
        diff_array = numpy.array([-1, 1])
        deltas = scipy.signal.correlate(sorted_array, diff_array, mode='valid')

        max_delta_index = numpy.argmax(deltas)

        #Try to return the average of the maximum delta
        if deltas[max_delta_index] > 0:
            return array_type((sorted_array[max_delta_index+1] +
                               sorted_array[max_delta_index])/2.0)

    #Else, all deltas are too small so go one smaller or one larger than the
    #min or max.  Catching an exception in case there's an overflow.
    try:
        return sorted_array[0]-1
    except OverflowError:
        return sorted_array[-1]+1


def create_rat_uri(dataset_uri, attr_dict, column_name):
    """
    URI wrapper for create_rat

    Args:
        dataset_uri (string): a GDAL raster dataset to create the RAT for (...)
        attr_dict (dict): a dictionary with keys that point to a primitive type
           {integer_id_1: value_1, ... integer_id_n: value_n}
        column_name (string): a string for the column name that maps the values

    """
    dataset = gdal.Open(dataset_uri, gdal.GA_Update)
    create_rat(dataset, attr_dict, column_name)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None


def create_rat(dataset, attr_dict, column_name):
    """
    Create a raster attribute table

    Args:
        dataset (?): a GDAL raster dataset to create the RAT for (...)
        attr_dict (dict): a dictionary with keys that point to a primitive type
           {integer_id_1: value_1, ... integer_id_n: value_n}
        column_name (string): a string for the column name that maps the values

    Returns:
        dataset (?): a GDAL raster dataset with an updated RAT

    """

    band = dataset.GetRasterBand(1)

    # If there was already a RAT associated with this dataset it will be blown
    # away and replaced by a new one
    L.warning('Blowing away any current raster attribute table')
    rat = gdal.RasterAttributeTable()

    rat.SetRowCount(len(attr_dict))

    # create columns
    rat.CreateColumn('Value', gdal.GFT_Integer, gdal.GFU_MinMax)
    rat.CreateColumn(column_name, gdal.GFT_String, gdal.GFU_Name)

    row_count = 0
    for key in sorted(attr_dict.keys()):
        rat.SetValueAsInt(row_count, 0, int(key))
        rat.SetValueAsString(row_count, 1, attr_dict[key])
        row_count += 1

    band.SetDefaultRAT(rat)
    return dataset


def get_raster_properties_uri(dataset_uri):
    """
    Wrapper function for get_raster_properties() that passes in the dataset
    URI instead of the datasets itself

    Args:
        dataset_uri (string): a URI to a GDAL raster dataset

    Returns:
        value (dictionary): a dictionary with the properties stored under
            relevant keys. The current list of things returned is:
            width (w-e pixel resolution), height (n-s pixel resolution),
            XSize, YSize
    """
    dataset = gdal.Open(dataset_uri)
    value = get_raster_properties(dataset)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return value


def get_raster_properties(dataset):
    """
    Get the width, height, X size, and Y size of the dataset and return the
    values in a dictionary.
    *This function can be expanded to return more properties if needed*

    Args:
       dataset (?): a GDAL raster dataset to get the properties from

    Returns:
        dataset_dict (dictionary): a dictionary with the properties stored
            under relevant keys. The current list of things returned is:
            width (w-e pixel resolution), height (n-s pixel resolution),
            XSize, YSize
    """
    dataset_dict = {}
    geo_transform = dataset.GetGeoTransform()
    dataset_dict['width'] = float(geo_transform[1])
    dataset_dict['height'] = float(geo_transform[5])
    dataset_dict['x_size'] = dataset.GetRasterBand(1).XSize
    dataset_dict['y_size'] = dataset.GetRasterBand(1).YSize
    return dataset_dict

def reproject_dataset_uri(
        original_dataset_uri, pixel_spacing, output_wkt, resampling_method,
        output_uri):
    """
    A function to reproject and resample a GDAL dataset given an output
    pixel size and output reference. Will use the datatype and nodata value
    from the original dataset.

    Args:
        original_dataset_uri (string): a URI to a gdal Dataset to written to
            disk
        pixel_spacing (?): output dataset pixel size in projected linear units
        output_wkt (?): output project in Well Known Text
        resampling_method (string): a string representing the one of the
            following resampling methods:
            "nearest|bilinear|cubic|cubic_spline|lanczos"
        output_uri (string): location on disk to dump the reprojected dataset

    Returns:
        projected_dataset (?): reprojected dataset
            (Note from Will: I possibly mislabeled this: looks like it's
                saved to file, with nothing returned)
    """

    # A dictionary to map the resampling method input string to the gdal type
    resample_dict = {
        "nearest": gdal.GRA_NearestNeighbour,
        "nearest_neighbor": gdal.GRA_NearestNeighbour,
        "near": gdal.GRA_NearestNeighbour,
        "bilinear": gdal.GRA_Bilinear,
        "cubic": gdal.GRA_Cubic,
        "cubic_spline": gdal.GRA_CubicSpline,
        "lanczos": gdal.GRA_Lanczos,
        "average": gdal.GRA_Average,
    }

    # Get the nodata value and datatype from the original dataset
    output_type = get_datatype_from_uri(original_dataset_uri)
    out_nodata = hb.get_nodata_from_uri(original_dataset_uri)

    original_dataset = gdal.Open(original_dataset_uri)

    original_wkt = original_dataset.GetProjection()

    # Create a virtual raster that is projected based on the output WKT. This
    # vrt does not save to disk and is used to get the proper projected bounding
    # box and size.
    vrt = gdal.AutoCreateWarpedVRT(
        original_dataset, None, output_wkt, gdal.GRA_Bilinear)

    geo_t = vrt.GetGeoTransform()
    x_size = vrt.RasterXSize # Raster xsize
    y_size = vrt.RasterYSize # Raster ysize

    # Calculate the extents of the projected dataset. These values will be used
    # to properly set the resampled size for the output dataset
    (ulx, uly) = (geo_t[0], geo_t[3])
    (lrx, lry) = (geo_t[0] + geo_t[1] * x_size, geo_t[3] + geo_t[5] * y_size)

    gdal_driver = gdal.GetDriverByName('GTiff')

    # Create the output dataset to receive the projected output, with the proper
    # resampled arrangement.
    output_dataset = gdal_driver.Create(
        output_uri, int((lrx - ulx)/pixel_spacing),
        int((uly - lry)/pixel_spacing), 1, output_type,
        options=['BIGTIFF=IF_SAFER'])

    # Set the nodata value for the output dataset
    output_dataset.GetRasterBand(1).SetNoDataValue(float(out_nodata))

    # Calculate the new geotransform
    output_geo = (ulx, pixel_spacing, geo_t[2], uly, geo_t[4], -pixel_spacing)

    # Set the geotransform
    output_dataset.SetGeoTransform(output_geo)
    output_dataset.SetProjection(output_wkt)

    # Perform the projection/resampling
    gdal.ReprojectImage(
        original_dataset, output_dataset, original_wkt, output_wkt,
        resample_dict[resampling_method])

    output_dataset.FlushCache()

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(output_dataset)
    output_dataset = None

    calculate_raster_stats_uri(output_uri)

def unique_raster_values_uri(dataset_uri):
    """
    Returns a list of the unique integer values on the given dataset

    Args:
        dataset_uri (string): a uri to a gdal dataset of some integer type

    Returns:
        value (list): a list of dataset's unique non-nodata values
    """

    dataset = gdal.Open(dataset_uri)
    value = unique_raster_values(dataset)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return value


def unique_raster_values(dataset):
    """
    Returns a list of the unique integer values on the given dataset

    Args:
        dataset (?): a gdal dataset of some integer type

    Returns:
        unique_list (list): a list of dataset's unique non-nodata values

    """

    band, nodata = extract_band_and_nodata(dataset)
    n_rows = band.YSize
    unique_values = numpy.array([])
    for row_index in range(n_rows):
        array = band.ReadAsArray(0, row_index, band.XSize, 1)[0]
        array = numpy.append(array, unique_values)
        unique_values = numpy.unique(array)

    unique_list = list(unique_values)
    if nodata in unique_list:
        unique_list.remove(nodata)
    return unique_list


def get_rat_as_dictionary_uri(dataset_uri):
    """
    Returns the RAT of the first band of dataset as a dictionary.

    Args:
        dataset (?): a GDAL dataset that has a RAT associated with the first
            band

    Returns:
        value (dictionary): a 2D dictionary where the first key is the column
            name and second is the row number

    """

    dataset = gdal.Open(dataset_uri)
    value = get_rat_as_dictionary(dataset)

    #Make sure the dataset is closed and cleaned up
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return value


def get_rat_as_dictionary(dataset):
    """
    Returns the RAT of the first band of dataset as a dictionary.

    Args:
        dataset (?): a GDAL dataset that has a RAT associated with the first
            band

    Returns:
        rat_dictionary (dictionary): a 2D dictionary where the first key is the
            column name and second is the row number

    """

    band = dataset.GetRasterBand(1)
    rat = band.GetDefaultRAT()
    n_columns = rat.GetColumnCount()
    n_rows = rat.GetRowCount()
    rat_dictionary = {}

    for col_index in range(n_columns):
        #Initialize an empty list to store row data and figure out the type
        #of data stored in that column.
        col_type = rat.GetTypeOfCol(col_index)
        col_name = rat.GetNameOfCol(col_index)
        rat_dictionary[col_name] = []

        #Now burn through all the rows to populate the column
        for row_index in range(n_rows):
            #This bit of python ugliness handles the known 3 types of gdal
            #RAT fields.
            if col_type == gdal.GFT_Integer:
                value = rat.GetValueAsInt(row_index, col_index)
            elif col_type == gdal.GFT_Real:
                value = rat.GetValueAsDouble(row_index, col_index)
            else:
                #If the type is not int or real, default to a string,
                #I think this is better than testing for a string and raising
                #an exception if not
                value = rat.GetValueAsString(row_index, col_index)

            rat_dictionary[col_name].append(value)

    return rat_dictionary

def reclassify_dataset_uri(
        dataset_uri, value_map, raster_out_uri, out_datatype, out_nodata,
        exception_flag='none', assert_dataset_projected=True):
    """
    A function to reclassify values in dataset to any output type. If there are
    values in the dataset that are not in value map, they will be mapped to
    out_nodata.

    Args:
        dataset_uri (string): a uri to a gdal dataset
        value_map (dictionary): a dictionary of values of
            {source_value: dest_value, ...}
            where source_value's type is a postive integer type and dest_value
            is of type out_datatype.
        raster_out_uri (string): the uri for the output raster
        out_datatype (?): the type for the output dataset
        out_nodata (?): the nodata value for the output raster.  Must be the
            same type as out_datatype

    Keyword Args:
        exception_flag (string): either 'none' or 'values_required'.
            If 'values_required' raise an exception if there is a value in the
            raster that is not found in value_map
        assert_dataset_projected (boolean): if True this operation will
            test if the input dataset is not projected and raise an exception
            if so.

    Returns:
        reclassified_dataset (?): the new reclassified dataset GDAL raster

    Raises:
        Exception: if exception_flag == 'values_required' and the value from
           'key_raster' is not a key in 'attr_dict'

    """

    nodata = hb.get_nodata_from_uri(dataset_uri)

    def map_dataset_to_value(original_values):
        """Converts a block of original values to the lookup values"""
        all_mapped = numpy.empty(original_values.shape, dtype=numpy.bool)
        out_array = numpy.empty(original_values.shape, dtype=numpy.float)
        for key, value in value_map.items():
            mask = original_values == key
            all_mapped = all_mapped | mask
            out_array[mask] = value
        nodata_mask = original_values == nodata
        all_mapped = all_mapped | nodata_mask
        out_array[nodata_mask] = out_nodata
        if not all_mapped.all() and exception_flag == 'values_required':
            raise Exception(
                'There was not a value for at least the following codes '
                'codes %s for this file %s.\nNodata value is: %s' % (
                    str(numpy.unique(original_values[~all_mapped])),
                    dataset_uri, str(nodata)))
        return out_array

    out_pixel_size = get_cell_size_from_uri(dataset_uri)
    vectorize_datasets(
        [dataset_uri], map_dataset_to_value,
        raster_out_uri, out_datatype, out_nodata, out_pixel_size,
        "intersection", dataset_to_align_index=0,
        vectorize_op=False, assert_datasets_projected=assert_dataset_projected)

def reclassify_dataset(
        dataset, value_map, raster_out_uri, out_datatype, out_nodata,
        exception_flag='none'):

    """
    An efficient function to reclassify values in a positive int dataset type
    to any output type.  If there are values in the dataset that are not in
    value map, they will be mapped to out_nodata.

    Args:
        dataset (?): a gdal dataset of some int type
        value_map (dict): a dictionary of values of
            {source_value: dest_value, ...}
            where source_value's type is a postive integer type and dest_value
            is of type out_datatype.
        raster_out_uri (string): the uri for the output raster
        out_datatype (?): the type for the output dataset
        out_nodata (?): the nodata value for the output raster.  Must be the
            same type as out_datatype

    Keyword Args:
        exception_flag (string): either 'none' or 'values_required'.
            If 'values_required' raise an exception if there is a value in the
            raster that is not found in value_map

    Returns:
        reclassified_dataset (?): the new reclassified dataset GDAL raster

    Raises:
        Exception: if exception_flag == 'values_required' and the value from
           'key_raster' is not a key in 'attr_dict'
    """

    out_dataset = hb.new_raster_from_base(
        dataset, raster_out_uri, 'GTiff', out_nodata, out_datatype)
    out_band = out_dataset.GetRasterBand(1)

    in_band, in_nodata = extract_band_and_nodata(dataset)
    in_band.ComputeStatistics(0)

    dataset_max = in_band.GetMaximum()

    #Make an array the same size as the max entry in the dictionary of the same
    #type as the output type.  The +2 adds an extra entry for the nodata values
    #The dataset max ensures that there are enough values in the array
    valid_set = set(value_map.keys())
    map_array_size = max(dataset_max, max(valid_set)) + 2
    valid_set.add(map_array_size - 1) #add the index for nodata
    map_array = numpy.empty(
        (1, map_array_size), dtype=type(list(value_map.values())[0]))
    map_array[:] = out_nodata

    for key, value in value_map.items():
        map_array[0, key] = value

    for row_index in range(in_band.YSize):
        row_array = in_band.ReadAsArray(0, row_index, in_band.XSize, 1)

        #It's possible for in_nodata to be None if the original raster
        #is none, we need to skip the index trick in that case.
        if in_nodata != None:
            #Remaps pesky nodata values the last index in map_array
            row_array[row_array == in_nodata] = map_array_size - 1

        if exception_flag == 'values_required':
            unique_set = set(row_array[0])
            if not unique_set.issubset(valid_set):
                undefined_set = unique_set.difference(valid_set)
                raise UndefinedValue(
                    "The following values were in the raster but not in the "
                    "value_map %s" % (list(undefined_set)))

        row_array = map_array[numpy.ix_([0], row_array[0])]
        out_band.WriteArray(row_array, 0, row_index)

    out_dataset.FlushCache()
    return out_dataset

def load_memory_mapped_array(dataset_uri, memory_file, array_type=None):
    """
    This function loads the first band of a dataset into a memory mapped
    array.

    Args:
        dataset_uri (string): the GDAL dataset to load into a memory mapped
            array
        memory_uri (string): a path to a file OR a file-like object that will
            be used to hold the memory map. It is up to the caller to create
            and delete this file.

    Keyword Args:
        array_type (?): the type of the resulting array, if None defaults
            to the type of the raster band in the dataset

    Returns:
        memory_array (memmap numpy array): a memmap numpy array of the data
            contained in the first band of dataset_uri

    """

    dataset = gdal.Open(dataset_uri)
    band = dataset.GetRasterBand(1)
    n_rows = dataset.RasterYSize
    n_cols = dataset.RasterXSize

    if array_type == None:
        try:
            dtype = hb.GDAL_TO_NUMPY_TYPE[band.DataType]
        except KeyError:
            raise TypeError('Unknown GDAL type %s' % band.DataType)
    else:
        dtype = array_type

    memory_array = numpy.memmap(
        memory_file, dtype=dtype, mode='w+', shape=(n_rows, n_cols))

    band.ReadAsArray(buf_obj=memory_array)

    #Make sure the dataset is closed and cleaned up
    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None

    return memory_array


def calculate_slope(
        dem_dataset_uri, slope_uri, aoi_uri=None, process_pool=None):
    """
    Generates raster maps of slope.  Follows the algorithm described here:
    http://webhelp.esri.com/arcgiSDEsktop/9.3/index.cfm?TopicName=How%20Slope%20works

    Args:
        dem_dataset_uri (string): a URI to a  single band raster of z values.
        slope_uri (string): a path to the output slope uri in percent.

    Keyword Args:
        aoi_uri (string): a uri to an AOI input
        process_pool (?): a process pool for multiprocessing

    Returns:
        nothing

    """

    out_pixel_size = get_cell_size_from_uri(dem_dataset_uri)
    dem_nodata = hb.get_nodata_from_uri(dem_dataset_uri)

    dem_small_uri = hb.temporary_filename(suffix='.tif', remove_at_exit=True)
    #cast the dem to a floating point one if it's not already
    dem_float_nodata = float(dem_nodata)

    vectorize_datasets(
        [dem_dataset_uri], lambda x: x.astype(numpy.float32), dem_small_uri,
        gdal.GDT_Float32, dem_float_nodata, out_pixel_size, "intersection",
        dataset_to_align_index=0, aoi_uri=aoi_uri, process_pool=process_pool,
        vectorize_op=False)

    slope_nodata = -9999.0
    hb.new_raster_from_base_uri(
        dem_small_uri, slope_uri, 'GTiff', slope_nodata, gdal.GDT_Float32)
    hb._cython_calculate_slope(dem_small_uri, slope_uri)
    calculate_raster_stats_uri(slope_uri)

    os.remove(dem_small_uri)



class DatasetUnprojected(Exception):
    """An exception in case a dataset is unprojected"""
    pass


class DifferentProjections(Exception):
    """An exception in case a set of datasets are not in the same projection"""
    pass



class NoDaemonProcess(multiprocessing.Process):
    """A class to make non-deamonic pools in case we want to have pools of
        pools"""
    # make 'daemon' attribute always return False
    def _get_daemon(self):
        return False

    def _set_daemon(self, value):
        pass
    daemon = property(_get_daemon, _set_daemon)


# We sub-class multiprocessing.pool.Pool instead of multiprocessing.Pool
# because the latter is only a wrapper function, not a proper class.
class PoolNoDaemon(multiprocessing.pool.Pool):
    Process = NoDaemonProcess


#Used to raise an exception if rasters, shapefiles, or both don't overlap
#in regions that should
class SpatialExtentOverlapException(Exception):
    """An exeception class for cases when datasets or datasources don't overlap
        in space"""
    pass


class UndefinedValue(Exception):
    """Used to indicate values that are not defined in dictionary
        structures"""
    pass


def align_dataset_list(
        dataset_uri_list, dataset_out_uri_list, resample_method_list,
        out_pixel_size, mode, dataset_to_align_index,
        dataset_to_bound_index=None, aoi_uri=None,
        assert_datasets_projected=True, option_list=None):
    print ('DEPRECATED function. Use geoprocessing.align_dataset_to_match or .align_list_of_datasets_to_match')

def get_lookup_from_table(table_uri, key_field):
    """
    Creates a python dictionary to look up the rest of the fields in a
    table file table indexed by the given key_field

    Args:
        table_uri (string): a URI to a dbf or csv file containing at
            least the header key_field
        key_field (?): (description)

    Returns:
        lookup_dict (dict): a dictionary of the form {key_field_0:
            {header_1: val_1_0, header_2: val_2_0, etc.}
            depending on the values of those fields

    """

    table_object = fileio.TableHandler(table_uri)
    raw_table_dictionary = table_object.get_table_dictionary(key_field.lower())

    lookup_dict = {}
    for key, sub_dict in raw_table_dictionary.items():
        key_value = _smart_cast(key)
        #Map an entire row to its lookup values
        lookup_dict[key_value] = (dict(
            [(sub_key, _smart_cast(value)) for sub_key, value in
             sub_dict.items()]))
    return lookup_dict


def get_lookup_from_csv(csv_table_uri, key_field):
    """
    Creates a python dictionary to look up the rest of the fields in a
    csv table indexed by the given key_field

    Args:
        csv_table_uri (string): a URI to a csv file containing at
            least the header key_field
        key_field (?): (description)

    Returns:
        lookup_dict (dict): returns a dictionary of the form {key_field_0:
            {header_1: val_1_0, header_2: val_2_0, etc.}
            depending on the values of those fields

    """

    def u(string):
        if type(string) is StringType:
            return str(string, 'utf-8')
        return string

    with open(csv_table_uri, 'rU') as csv_file:
        csv_reader = csv.reader(csv_file)
        header_row = [u(s) for s in next(csv_reader)]
        key_index = header_row.index(key_field)
        #This makes a dictionary that maps the headers to the indexes they
        #represent in the soon to be read lines
        index_to_field = dict(list(zip(list(range(len(header_row))), header_row)))

        lookup_dict = {}
        for line_num, line in enumerate(csv_reader):
            try:
                key_value = _smart_cast(line[key_index])
            except IndexError as error:
                L.error('CSV line %s (%s) should have index %s', line_num,
                             line, key_index)
                raise error
            #Map an entire row to its lookup values
            lookup_dict[key_value] = (
                dict([(index_to_field[index], _smart_cast(value))
                      for index, value in zip(list(range(len(line))), line)]))
        return lookup_dict


def extract_datasource_table_by_key(datasource_uri, key_field):
    """
    Create a dictionary lookup table of the features in the attribute table
    of the datasource referenced by datasource_uri.

    Args:
        datasource_uri (string): a uri to an OGR datasource
        key_field (?): a field in datasource_uri that refers to a key value
            for each row such as a polygon id.

    Returns:
        attribute_dictionary (dict): returns a dictionary of the
            form {key_field_0: {field_0: value0, field_1: value1}...}

    """

    #Pull apart the datasource
    datasource = ogr.Open(datasource_uri)
    layer = datasource.GetLayer()
    layer_def = layer.GetLayerDefn()

    #Build up a list of field names for the datasource table
    field_names = []
    for field_id in range(layer_def.GetFieldCount()):
        field_def = layer_def.GetFieldDefn(field_id)
        field_names.append(field_def.GetName())

    #Loop through each feature and build up the dictionary representing the
    #attribute table
    attribute_dictionary = {}
    for feature_index in range(layer.GetFeatureCount()):
        feature = layer.GetFeature(feature_index)
        feature_fields = {}
        for field_name in field_names:
            feature_fields[field_name] = feature.GetField(field_name)
        key_value = feature.GetField(key_field)
        attribute_dictionary[key_value] = feature_fields

    #Explictly clean up the layers so the files close
    layer = None
    datasource = None
    return attribute_dictionary


def get_geotransform_uri(dataset_uri):
    """
    Get the geotransform from a gdal dataset

    Args:
        dataset_uri (string): a URI for the dataset

    Returns:
        geotransform (?): a dataset geotransform list

    """

    dataset = gdal.Open(dataset_uri)
    geotransform = dataset.GetGeoTransform()
    gdal.Dataset.__swig_destroy__(dataset)
    return geotransform


def get_spatial_ref_uri(datasource_uri):
    """
    Get the spatial reference of an OGR datasource

    Args:
        datasource_uri (string): a URI to an ogr datasource

    Returns:
        spat_ref (?): a spatial reference

    """

    shape_datasource = ogr.Open(datasource_uri)
    layer = shape_datasource.GetLayer()
    spat_ref = layer.GetSpatialRef()
    return spat_ref


def copy_datasource_uri(shape_uri, copy_uri):
    """
    Create a copy of an ogr shapefile

    Args:
        shape_uri (string): a uri path to the ogr shapefile that is to be
            copied
        copy_uri (string): a uri path for the destination of the copied
            shapefile

    Returns:
        nothing

    """
    if os.path.isfile(copy_uri):
        os.remove(copy_uri)

    shape = ogr.Open(shape_uri)
    drv = ogr.GetDriverByName('ESRI Shapefile')
    drv.CopyDataSource(shape, copy_uri)


def vectorize_points_uri(
        shapefile_uri, field, output_uri, interpolation='nearest'):
    """
    A wrapper function for raster_utils.vectorize_points, that allows for uri
    passing

    Args:
        shapefile_uri (string): a uri path to an ogr shapefile
        field (string): a string for the field name
        output_uri (string): a uri path for the output raster
        interpolation (string): interpolation method to use on points, default
            is 'nearest'

    Returns:
        nothing

    """

    datasource = ogr.Open(shapefile_uri)
    output_raster = gdal.Open(output_uri, 1)
    vectorize_points(
        datasource, field, output_raster, interpolation=interpolation)

def dictionary_to_point_shapefile(dict_data, layer_name, output_uri):
    """
    Creates a point shapefile from a dictionary. The point shapefile created
    is not projected and uses latitude and longitude for its geometry.

    Args:
        dict_data (dict): a python dictionary with keys being unique id's that
            point to sub-dictionarys that have key-value pairs. These inner
            key-value pairs will represent the field-value pair for the point
            features. At least two fields are required in the sub-dictionaries,
            All the keys in the sub dictionary should have the same name and
            order. All the values in the sub dictionary should have the same
            type 'lati' and 'long'. These fields determine the geometry of the
            point
            0 : {'lati':97, 'long':43, 'field_a':6.3, 'field_b':'Forest',...},
            1 : {'lati':55, 'long':51, 'field_a':6.2, 'field_b':'Crop',...},
            2 : {'lati':73, 'long':47, 'field_a':6.5, 'field_b':'Swamp',...}
        layer_name (string): a python string for the name of the layer
        output_uri (string): a uri for the output path of the point shapefile

    Returns:
        nothing

    """

    # If the output_uri exists delete it
    if os.path.isfile(output_uri):
        os.remove(output_uri)
    elif os.path.isdir(output_uri):
        shutil.rmtree(output_uri)

    output_driver = ogr.GetDriverByName('ESRI Shapefile')
    output_datasource = output_driver.CreateDataSource(output_uri)

    # Set the spatial reference to WGS84 (lat/long)
    source_sr = osr.SpatialReference()
    source_sr.SetWellKnownGeogCS("WGS84")

    output_layer = output_datasource.CreateLayer(
        layer_name, source_sr, ogr.wkbPoint)

    # Outer unique keys
    outer_keys = list(dict_data.keys())

    # Construct a list of fields to add from the keys of the inner dictionary
    field_list = list(dict_data[outer_keys[0]].keys())

    # Create a dictionary to store what variable types the fields are
    type_dict = {}
    for field in field_list:
        # Get a value from the field
        val = dict_data[outer_keys[0]][field]
        # Check to see if the value is a String of characters or a number. This
        # will determine the type of field created in the shapefile
        if isinstance(val, str):
            type_dict[field] = 'str'
        else:
            type_dict[field] = 'number'

    for field in field_list:
        field_type = None
        # Distinguish if the field type is of type String or other. If Other, we
        # are assuming it to be a float
        if type_dict[field] == 'str':
            field_type = ogr.OFTString
        else:
            field_type = ogr.OFTReal

        output_field = ogr.FieldDefn(field, field_type)
        output_layer.CreateField(output_field)

    # For each inner dictionary (for each point) create a point and set its
    # fields
    for point_dict in dict_data.values():
        latitude = float(point_dict['lati'])
        longitude = float(point_dict['long'])

        geom = ogr.Geometry(ogr.wkbPoint)
        geom.AddPoint_2D(longitude, latitude)

        output_feature = ogr.Feature(output_layer.GetLayerDefn())

        for field_name in point_dict:
            field_index = output_feature.GetFieldIndex(field_name)
            output_feature.SetField(field_index, point_dict[field_name])

        output_feature.SetGeometryDirectly(geom)
        output_layer.CreateFeature(output_feature)
        output_feature = None

    output_layer.SyncToDisk()

def get_datasource_projection_wkt_uri(input_path):
    # Convenience wrapper to have parrallel names.
    spatial_ref = get_spatial_ref_uri(input_path)
    wkt = spatial_ref.ExportToWkt()
    return wkt


def unique_raster_values_count(dataset_uri, ignore_nodata=True):
    """
    Return a dict from unique int values in the dataset to their frequency.

    Args:
        dataset_uri (string): uri to a gdal dataset of some integer type

    Keyword Args:
        ignore_nodata (boolean): if set to false, the nodata count is also
            included in the result

    Returns:
        itemfreq (dict): values to count.
    """

    dataset = gdal.Open(dataset_uri)
    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue()

    itemfreq = collections.defaultdict(int)
    for row_index in range(band.YSize):
        cur_array = band.ReadAsArray(0, row_index, band.XSize, 1)[0]
        for val in numpy.unique(cur_array):
            if ignore_nodata and val == nodata:
                continue
            itemfreq[val] += numpy.count_nonzero(cur_array == val)

    band = None
    gdal.Dataset.__swig_destroy__(dataset)
    dataset = None
    return itemfreq

def email_report(message, email_address):
    """
    A simple wrapper around an SMTP call.  Can be used to send text messages
    if the email address is constructed as the following:

    Alltel [10-digit phone number]@message.alltel.com
    AT&T (formerly Cingular) [10-digit phone number]@txt.att.net
    Boost Mobile [10-digit phone number]@myboostmobile.com
    Nextel (now Sprint Nextel) [10-digit telephone number]@messaging.nextel.com
    Sprint PCS (now Sprint Nextel) [10-digit phone number]@messaging.sprintpcs.com
    T-Mobile [10-digit phone number]@tmomail.net
    US Cellular [10-digit phone number]email.uscc.net (SMS)
    Verizon [10-digit phone number]@vtext.com
    Virgin Mobile USA [10-digit phone number]@vmobl.com

    Args:
        message (string): the message to send
        email_address (string): where to send the message

    Returns:
        nothing

    """

    try:
        server = smtplib.SMTP('smtp.gmail.com:587')
        server.starttls()
        server.login('natcapsoftwareteam@gmail.com', 'assman64')
        server.sendmail('natcapsoftwareteam@gmail.com', email_address, message)
        server.quit()
    except smtplib.socket.gaierror:
        L.warning("Can't connect to email server, no report will be sent.")


def convolve_2d_uri(signal_uri, kernel_uri, output_uri, ignore_nodata=True):
    """
    Does a direct convolution on a predefined kernel with the values in
    signal_uri

    Args:
        signal_uri (string): a filepath to a gdal dataset that's the
            souce input.
        kernel_uri (string): a filepath to a gdal dataset that's the
            souce input.
        output_uri (string): a filepath to the gdal dataset
            that's the convolution output of signal and kernel
            that is the same size and projection of signal_uri.
        ignore_nodata (Boolean): If set to true, the nodata values in
            signal_uri and kernel_uri are treated as 0 in the convolution,
            otherwise the raw nodata values are used.  Default True.

    Returns:
        nothing

    """

    output_nodata = -9999

    tmp_signal_uri = hb.temporary_filename()
    tile_dataset_uri(signal_uri, tmp_signal_uri, 256)

    tmp_kernel_uri = hb.temporary_filename()
    tile_dataset_uri(kernel_uri, tmp_kernel_uri, 256)

    hb.new_raster_from_base_uri(
        signal_uri, output_uri, 'GTiff', output_nodata, gdal.GDT_Float32,
        fill_value=0)

    signal_ds = gdal.Open(tmp_signal_uri)
    signal_band = signal_ds.GetRasterBand(1)
    signal_block_col_size, signal_block_row_size = signal_band.GetBlockSize()
    signal_nodata = hb.get_nodata_from_uri(tmp_signal_uri)

    kernel_ds = gdal.Open(tmp_kernel_uri)
    kernel_band = kernel_ds.GetRasterBand(1)
    kernel_block_col_size, kernel_block_row_size = kernel_band.GetBlockSize()
    #make kernel block size a little larger if possible
    kernel_block_col_size *= 3
    kernel_block_row_size *= 3

    kernel_nodata = hb.get_nodata_from_uri(tmp_kernel_uri)

    output_ds = gdal.Open(output_uri, gdal.GA_Update)
    output_band = output_ds.GetRasterBand(1)

    n_rows_signal = signal_band.YSize
    n_cols_signal = signal_band.XSize

    n_rows_kernel = kernel_band.YSize
    n_cols_kernel = kernel_band.XSize

    n_global_block_rows_signal = (
        int(math.ceil(float(n_rows_signal) / signal_block_row_size)))
    n_global_block_cols_signal = (
        int(math.ceil(float(n_cols_signal) / signal_block_col_size)))

    n_global_block_rows_kernel = (
        int(math.ceil(float(n_rows_kernel) / kernel_block_row_size)))
    n_global_block_cols_kernel = (
        int(math.ceil(float(n_cols_kernel) / kernel_block_col_size)))

    last_time = time.time()
    for global_block_row in range(n_global_block_rows_signal):
        current_time = time.time()
        if current_time - last_time > 5.0:
            L.info(
                "convolution %.1f%% complete", global_block_row /
                                               float(n_global_block_rows_signal) * 100)
            last_time = current_time
        for global_block_col in range(n_global_block_cols_signal):
            signal_xoff = global_block_col * signal_block_col_size
            signal_yoff = global_block_row * signal_block_row_size
            win_xsize = min(signal_block_col_size, n_cols_signal - signal_xoff)
            win_ysize = min(signal_block_row_size, n_rows_signal - signal_yoff)

            signal_block = signal_band.ReadAsArray(
                xoff=signal_xoff, yoff=signal_yoff,
                win_xsize=win_xsize, win_ysize=win_ysize)

            if ignore_nodata:
                signal_nodata_mask = signal_block == signal_nodata
                signal_block[signal_nodata_mask] = 0.0

            for kernel_block_row_index in range(n_global_block_rows_kernel):
                for kernel_block_col_index in range(
                        n_global_block_cols_kernel):
                    kernel_yoff = kernel_block_row_index*kernel_block_row_size
                    kernel_xoff = kernel_block_col_index*kernel_block_col_size

                    kernel_win_ysize = min(
                        kernel_block_row_size, n_rows_kernel - kernel_yoff)
                    kernel_win_xsize = min(
                        kernel_block_col_size, n_cols_kernel - kernel_xoff)

                    left_index_raster = (
                            signal_xoff - n_cols_kernel / 2 + kernel_xoff)
                    right_index_raster = (
                            signal_xoff - n_cols_kernel / 2 + kernel_xoff +
                            win_xsize + kernel_win_xsize - 1)
                    top_index_raster = (
                            signal_yoff - n_rows_kernel / 2 + kernel_yoff)
                    bottom_index_raster = (
                            signal_yoff - n_rows_kernel / 2 + kernel_yoff +
                            win_ysize + kernel_win_ysize - 1)

                    #it's possible that the piece of the integrating kernel
                    #doesn't even affect the final result, we can just skip
                    if (right_index_raster < 0 or
                            bottom_index_raster < 0 or
                            left_index_raster > n_cols_signal or
                            top_index_raster > n_rows_signal):
                        continue

                    kernel_block = kernel_band.ReadAsArray(
                        xoff=kernel_xoff, yoff=kernel_yoff,
                        win_xsize=kernel_win_xsize, win_ysize=kernel_win_ysize)

                    if ignore_nodata:
                        kernel_nodata_mask = (kernel_block == kernel_nodata)
                        kernel_block[kernel_nodata_mask] = 0.0

                    result = scipy.signal.fftconvolve(
                        signal_block, kernel_block, 'full')

                    left_index_result = 0
                    right_index_result = result.shape[1]
                    top_index_result = 0
                    bottom_index_result = result.shape[0]

                    #we might abut the edge of the raster, clip if so
                    if left_index_raster < 0:
                        left_index_result = -left_index_raster
                        left_index_raster = 0
                    if top_index_raster < 0:
                        top_index_result = -top_index_raster
                        top_index_raster = 0

                    if right_index_raster > n_cols_signal:
                        right_index_result -= right_index_raster - n_cols_signal
                        right_index_raster = n_cols_signal
                    if bottom_index_raster > n_rows_signal:
                        bottom_index_result -= (
                                bottom_index_raster - n_rows_signal)
                        bottom_index_raster = n_rows_signal

                    current_output = output_band.ReadAsArray(
                        xoff=left_index_raster, yoff=top_index_raster,
                        win_xsize=right_index_raster-left_index_raster,
                        win_ysize=bottom_index_raster-top_index_raster)

                    potential_nodata_signal_array = signal_band.ReadAsArray(
                        xoff=left_index_raster, yoff=top_index_raster,
                        win_xsize=right_index_raster-left_index_raster,
                        win_ysize=bottom_index_raster-top_index_raster)
                    nodata_mask = potential_nodata_signal_array == signal_nodata

                    output_array = result[
                                   top_index_result:bottom_index_result,
                                   left_index_result:right_index_result] + current_output
                    output_array[nodata_mask] = output_nodata

                    output_band.WriteArray(
                        output_array, xoff=left_index_raster,
                        yoff=top_index_raster)

    signal_band = None
    gdal.Dataset.__swig_destroy__(signal_ds)
    signal_ds = None
    os.remove(tmp_signal_uri)

def tile_dataset_uri(in_uri, out_uri, blocksize):
    """
    Takes an existing gdal dataset and resamples it into a tiled raster with
    blocks of blocksize X blocksize.

    Args:
        in_uri (string): dataset to base data from
        out_uri (string): output dataset
        blocksize (int): defines the side of the square for the raster, this
            seems to have a lower limit of 16, but is untested

    Returns:
        nothing

    """

    dataset = gdal.Open(in_uri)
    band = dataset.GetRasterBand(1)
    datatype_out = band.DataType
    nodata_out = hb.get_nodata_from_uri(in_uri)
    pixel_size_out = get_cell_size_from_uri(in_uri)
    dataset_options=[
        'TILED=YES', 'BLOCKXSIZE=%d' % blocksize, 'BLOCKYSIZE=%d' % blocksize,
        'BIGTIFF=IF_SAFER']
    vectorize_datasets(
        [in_uri], lambda x: x, out_uri, datatype_out,
        nodata_out, pixel_size_out, 'intersection',
        resample_method_list=None, dataset_to_align_index=None,
        dataset_to_bound_index=None, aoi_uri=None,
        assert_datasets_projected=False, process_pool=None, vectorize_op=False,
        datasets_are_pre_aligned=False, dataset_options=dataset_options)


def make_constant_raster_from_base_uri(
        base_dataset_uri, constant_value, out_uri, nodata_value=None,
        dataset_type=gdal.GDT_Float32):
    """
    A helper function that creates a new gdal raster from base, and fills
    it with the constant value provided.

    Args:
        base_dataset_uri (string): the gdal base raster
        constant_value (?): the value to set the new base raster to
        out_uri (string): the uri of the output raster

    Keyword Args:
        nodata_value (?): the value to set the constant raster's nodata
            value to.  If not specified, it will be set to constant_value - 1.0
        dataset_type (?): the datatype to set the dataset to, default
            will be a float 32 value.

    Returns:
        nothing

    """

    if nodata_value == None:
        nodata_value = constant_value - 1.0
    hb.new_raster_from_base_uri(
        base_dataset_uri, out_uri, 'GTiff', nodata_value,
        dataset_type)
    base_dataset = gdal.Open(out_uri, gdal.GA_Update)
    base_band = base_dataset.GetRasterBand(1)
    base_band.Fill(constant_value)

    base_band = None
    gdal.Dataset.__swig_destroy__(base_dataset)
    base_dataset = None

def smart_cast(value):
    """
    Attempts to cast value to a float, int, or leave it as string

    Args:
        value (?): (description)

    Returns:
        value (?): (description)
    """
    #If it's not a string, don't try to cast it because i got a bug
    #where all my floats were happily cast to ints
    if type(value) != str:
        return value
    for cast_function in [int, float]:
        try:
            return cast_function(value)
        except ValueError:
            pass
    for unicode_type in ['ascii', 'utf-8', 'latin-1']:
        try:
            return value.decode(unicode_type)
        except UnicodeDecodeError:
            pass
    L.warning("unknown encoding type encountered in _smart_cast: %s" % value)
    return value







def new_raster_from_base_pgp06(
        base_path, target_path, datatype, band_nodata_list,
        fill_value_list=None, n_rows=None, n_cols=None,
        gtiff_creation_options=hb.DEFAULT_GTIFF_CREATION_OPTIONS):
    """Create new GeoTIFF by coping spatial reference/geotransform of base.

    A convenience function to simplify the creation of a new raster from the
    basis of an existing one.  Depending on the input mode, one can create
    a new raster of the same dimensions, geotransform, and georeference as
    the base.  Other options are provided to change the raster dimensions,
    number of bands, nodata values, data type, and core GeoTIFF creation
    options.

    Parameters:
        base_path (string): path to existing raster.
        target_path (string): path to desired target raster.
        datatype: the pixel datatype of the output raster, for example
            gdal.GDT_Float32.  See the following header file for supported
            pixel types:
            http://www.gdal.org/gdal_8h.html#22e22ce0a55036a96f652765793fb7a4
        band_nodata_list (list): list of nodata values, one for each band, to
            set on target raster.  If value is 'None' the nodata value is not
            set for that band.  The number of target bands is inferred from
            the length of this list.
        fill_value_list (list): list of values to fill each band with. If None,
            no filling is done.
        n_rows (int): if not None, defines the number of target raster rows.
        n_cols (int): if not None, defines the number of target raster
            columns.
        gtiff_creation_options: a list of dataset options that gets
            passed to the gdal creation driver, overrides defaults

    Returns:
        None
    """
    base_raster = gdal.OpenEx(base_path)
    if n_rows is None:
        n_rows = base_raster.RasterYSize
    if n_cols is None:
        n_cols = base_raster.RasterXSize
    driver = gdal.GetDriverByName('GTiff')

    local_gtiff_creation_options = list(gtiff_creation_options)
    # PIXELTYPE is sometimes used to define signed vs. unsigned bytes and
    # the only place that is stored is in the IMAGE_STRUCTURE metadata
    # copy it over if it exists and it not already defined by the input
    # creation options. It's okay to get this info from the first band since
    # all bands have the same datatype
    base_band = base_raster.GetRasterBand(1)
    metadata = base_band.GetMetadata('IMAGE_STRUCTURE')
    if 'PIXELTYPE' in metadata and not any(
            ['PIXELTYPE' in option for option in
             local_gtiff_creation_options]):
        local_gtiff_creation_options.append(
            'PIXELTYPE=' + metadata['PIXELTYPE'])

    block_size = base_band.GetBlockSize()
    # It's not clear how or IF we can determine if the output should be
    # striped or tiled.  Here we leave it up to the default inputs or if its
    # obviously not striped we tile.
    if not any(
            ['TILED' in option for option in local_gtiff_creation_options]):
        # TILED not set, so lets try to set it to a reasonable value
        if block_size[0] != n_cols:
            # if x block is not the width of the raster it *must* be tiled
            # otherwise okay if it's striped or tiled
            local_gtiff_creation_options.append('TILED=YES')

    if not any(
            ['BLOCK' in option for option in local_gtiff_creation_options]):
        # not defined, so lets copy what we know from the current raster
        local_gtiff_creation_options.extend([
            'BLOCKXSIZE=%d' % block_size[0],
            'BLOCKYSIZE=%d' % block_size[1]])

    base_band = None

    n_bands = len(band_nodata_list)
    target_raster = driver.Create(
        target_path.encode('utf-8'), n_cols, n_rows, n_bands, datatype,
        options=gtiff_creation_options)
    target_raster.SetProjection(base_raster.GetProjection())
    target_raster.SetGeoTransform(base_raster.GetGeoTransform())
    base_raster = None

    for index, nodata_value in enumerate(band_nodata_list):
        if nodata_value is None:
            continue
        target_band = target_raster.GetRasterBand(index + 1)
        try:
            target_band.SetNoDataValue(nodata_value.item())
        except AttributeError:
            target_band.SetNoDataValue(nodata_value)

    if fill_value_list is not None:
        for index, fill_value in enumerate(fill_value_list):
            if fill_value is None:
                continue
            target_band = target_raster.GetRasterBand(index + 1)
            target_band.Fill(fill_value)
            target_band = None

    target_raster = None




























































